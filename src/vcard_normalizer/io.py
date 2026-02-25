from __future__ import annotations

import logging
import re
from pathlib import Path

import vobject

logger = logging.getLogger(__name__)

# ── Pre-parse sanitisation ─────────────────────────────────────────────────────
#
# Real-world vCard exports — especially from Apple iCloud — contain lines that
# vobject's strict parser cannot handle. We fix them in plain text first.
#
# Known patterns (all from iCloud exports observed in the wild):
#
#   item1..ADR   double-dot group prefix  → strip prefix, keep property
#   item1.ADR    single-dot group prefix  → strip prefix, keep property
#   item1.X-*    Apple extension on group → drop line entirely
#   .ADR         bare leading dot         → strip the dot, keep property
#   .X-*         bare leading dot + X-    → drop line entirely

_ITEM_DOUBLE_DOT = re.compile(r"^item\d+\.\.", re.IGNORECASE)
_ITEM_SINGLE_STD = re.compile(r"^item\d+\.((?!X-)[A-Z])", re.IGNORECASE)
_ITEM_X_PROP     = re.compile(r"^item\d+\.X-", re.IGNORECASE)
_BARE_DOT_X      = re.compile(r"^\.(X-)", re.IGNORECASE)
_BARE_DOT_STD    = re.compile(r"^\.((?!X-)[A-Z])", re.IGNORECASE)


def _sanitise_vcf(data: str, source_label: str) -> str:
    """Clean up known malformed line patterns before vobject sees them."""
    lines = data.splitlines(keepends=True)
    out: list[str] = []
    skipped = fixed = 0

    for line in lines:
        # Drop itemN.X-* and bare .X-* lines — Apple extension noise
        if _ITEM_X_PROP.match(line) or _BARE_DOT_X.match(line):
            skipped += 1
            continue

        # Fix itemN..PROP (double dot) → PROP
        if _ITEM_DOUBLE_DOT.match(line):
            line = _ITEM_DOUBLE_DOT.sub("", line)
            fixed += 1
        # Fix itemN.PROP (single dot, standard) → PROP
        elif _ITEM_SINGLE_STD.match(line):
            line = _ITEM_SINGLE_STD.sub(r"\1", line)
            fixed += 1
        # Fix .PROP (bare leading dot, standard) → PROP
        elif _BARE_DOT_STD.match(line):
            line = _BARE_DOT_STD.sub(r"\1", line)
            fixed += 1

        out.append(line)

    if skipped or fixed:
        logger.debug("%s: %d line(s) fixed, %d dropped", source_label, fixed, skipped)

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
