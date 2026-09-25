from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

import vobject

logger = logging.getLogger(__name__)

# ── Pre-parse sanitisation ─────────────────────────────────────────────────────
#
# Apple/iCloud commonly uses grouped properties:
#
#   item1.TEL;TYPE=CELL:...
#   item1.X-ABLabel:iPhone
#   item2.ADR;TYPE=HOME:...
#   item2.X-ABADR:gb
#
# Older/problematic exports also contain ``item1..ADR``.  vobject is happier if
# the group prefix is removed, but blindly deleting the matching X-ABLabel loses
# useful semantics.  We therefore encode Apple group metadata into temporary,
# parser-safe X-VCS parameters on the standard property.  normalize.py consumes
# those parameters into the canonical model before proprietary stripping runs.

_GROUP_LINE = re.compile(
    r"^(?P<group>item\d+)\.(?P<extra_dot>\.?)(?P<prop>[A-Z][A-Z0-9-]*)(?P<rest>[;:].*)$",
    re.IGNORECASE,
)
_BARE_DOT_X = re.compile(r"^\.X-", re.IGNORECASE)
_BARE_DOT_STD = re.compile(r"^\.((?!X-)[A-Z])", re.IGNORECASE)


def _b64_param(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _inject_param(line: str, name: str, value: str) -> str:
    """Add ``;NAME=value`` immediately before the first vCard value colon."""
    newline = ""
    if line.endswith("\r\n"):
        line, newline = line[:-2], "\r\n"
    elif line.endswith("\n"):
        line, newline = line[:-1], "\n"
    pos = line.find(":")
    if pos < 0:
        return line + newline
    return f"{line[:pos]};{name}={value}{line[pos:]}{newline}"


def _is_continuation(line: str) -> bool:
    """True for a folded continuation line (starts with a single space or tab)."""
    return line[:1] in (" ", "\t")


def _sanitise_vcf(data: str, source_label: str) -> str:
    """Repair malformed Apple group syntax while preserving useful metadata."""
    lines = data.splitlines(keepends=True)
    group_meta: dict[str, dict[str, str]] = {}

    # Pass 1: collect Apple's label/country metadata by group id.
    # Values may be folded (RFC 6350 §3.2), so gather continuation lines too.
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = _GROUP_LINE.match(body)
        if not match:
            continue
        prop = match.group("prop").upper()
        if prop not in {"X-ABLABEL", "X-ABADR"}:
            continue
        rest = match.group("rest")
        j = i + 1
        while j < len(lines) and _is_continuation(lines[j]):
            rest += lines[j].rstrip("\r\n")[1:]
            j += 1
        colon = rest.find(":")
        if colon < 0:
            continue
        value = rest[colon + 1 :].strip()
        if value:
            key = "label" if prop == "X-ABLABEL" else "adr"
            group_meta.setdefault(match.group("group").lower(), {})[key] = value

    out: list[str] = []
    skipped = fixed = preserved = 0
    # When a property line is dropped, its folded continuation lines must be
    # dropped with it.  Otherwise the parser unfolds them onto whichever kept
    # property precedes them (observed: Apple item1.X-ADDRESSING-GRAMMAR base64
    # appended to FN).
    dropping = False

    for line in lines:
        if _is_continuation(line):
            if dropping:
                skipped += 1
                continue
            out.append(line)
            continue
        dropping = False

        newline = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        body = line[:-len(newline)] if newline else line
        match = _GROUP_LINE.match(body)
        if match:
            group = match.group("group").lower()
            prop = match.group("prop").upper()

            # Preserve the small subset of Apple X-properties that carry actual
            # contact data. Attach the group's X-ABLabel as temporary metadata
            # so normalize.py can interpret Anniversary/Spouse/etc.
            if prop in {"X-ABDATE", "X-ABRELATEDNAMES"}:
                line = f"{prop}{match.group('rest')}{newline}"
                fixed += 1
                meta = group_meta.get(group, {})
                if meta.get("label"):
                    line = _inject_param(line, "X-VCS-APPLE-LABEL-B64", _b64_param(meta["label"]))
                    preserved += 1
                out.append(line)
                continue

            # Metadata lines have already been associated with their standard
            # property. Other grouped X-* extensions remain non-canonical noise.
            if prop.startswith("X-"):
                skipped += 1
                dropping = True
                continue

            # Strip itemN. (and the observed erroneous second dot) but retain
            # the standard property and its parameters/value.
            line = f"{prop}{match.group('rest')}{newline}"
            fixed += 1

            meta = group_meta.get(group, {})
            if prop in {"TEL", "EMAIL", "ADR", "URL"} and meta.get("label"):
                line = _inject_param(line, "X-VCS-APPLE-LABEL-B64", _b64_param(meta["label"]))
                preserved += 1
            if prop == "ADR" and meta.get("adr"):
                line = _inject_param(line, "X-VCS-APPLE-ADR-B64", _b64_param(meta["adr"]))
                preserved += 1

            out.append(line)
            continue

        # Bare malformed .X-* lines cannot be associated safely; drop them.
        if _BARE_DOT_X.match(line):
            skipped += 1
            dropping = True
            continue
        if _BARE_DOT_STD.match(line):
            line = _BARE_DOT_STD.sub(r"\1", line)
            fixed += 1

        out.append(line)

    if skipped or fixed or preserved:
        logger.debug(
            "%s: %d line(s) fixed, %d Apple metadata value(s) preserved, %d dropped",
            source_label,
            fixed,
            preserved,
            skipped,
        )

    return "".join(out)


# ── Public API ─────────────────────────────────────────────────────────────────

def read_vcards_from_files(
    paths: list[Path],
) -> list[tuple[vobject.base.Component, str]]:
    """Parse all .vcf files and return (vobject_component, source_label) pairs."""
    results: list[tuple[vobject.base.Component, str]] = []
    for p in paths:
        label = p.stem
        raw = p.read_text(encoding="utf-8", errors="replace")
        data = _sanitise_vcf(raw, label)
        for vc in vobject.readComponents(data, ignoreUnreadable=True):
            if vc.name.upper() == "VCARD":
                results.append((vc, label))
    return results


def collect_merge_sources(merge_dir: Path) -> list[Path]:
    """Return all .vcf files found directly inside merge_dir, sorted by name."""
    if not merge_dir.is_dir():
        return []
    return sorted(p for p in merge_dir.iterdir() if p.suffix.lower() == ".vcf")
