#!/usr/bin/env python3
"""preflight_merge.py — READ-ONLY dry run of a vCard Studio import.

Simulates exactly what "merge & deduplicate" (/api/process) would do with the
files currently in cards-in/ against the current cards-master/master.vcf, and
reports what would be lost or merged.  Writes nothing, moves nothing.

Usage (from the project root):
    python3 tools/preflight_merge.py            # uses local/vcard.conf region
    python3 tools/preflight_merge.py --region GB
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcard_normalizer.io import collect_merge_sources, read_vcards_from_files  # noqa: E402
from vcard_normalizer.normalize import normalize_cards  # noqa: E402
from vcard_normalizer.proprietary import DefaultStripper  # noqa: E402
from vcard_normalizer.formatters import (  # noqa: E402
    auto_tag_categories, classify_entities, normalize_phones_in_cards,
)
from vcard_normalizer.master import merge_import_into_master  # noqa: E402
from vcard_normalizer.dedupe import find_duplicate_clusters  # noqa: E402

# Properties normalize.py models (everything else is dropped on first save)
KEPT = {
    "BEGIN", "END", "VERSION", "PRODID", "FN", "N", "EMAIL", "TEL", "ORG", "TITLE",
    "BDAY", "ANNIVERSARY", "UID", "REV", "ADR", "RELATED", "CATEGORIES", "NOTE",
    "KIND", "GENDER", "X-VCARD-STUDIO-WAIVED", "X-IOS-GIVEN", "X-IOS-FAMILY",
}
_PROP = re.compile(r"^(?:item\d+\.+|\.)?([A-Za-z0-9-]+)[;:]")


def label(c) -> str:
    return c.fn or c.org or c.uid or "?"


def raw_property_census(files: list[Path]) -> tuple[Counter, dict[str, int]]:
    props: Counter = Counter()
    begins: dict[str, int] = {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        begins[f.name] = len(re.findall(r"^BEGIN:VCARD", text, re.M | re.I))
        for line in text.splitlines():
            if line[:1] in (" ", "\t"):
                continue  # folded continuation
            m = _PROP.match(line)
            if m:
                props[m.group(1).upper()] += 1
    return props, begins


def lost_fields(best, other) -> list[str]:
    """Fields merge_cluster_auto() does NOT carry from `other` into `best`."""
    out = []
    if other.addresses and not best.addresses:
        out.append("ADR")
    elif len(other.addresses) and other.addresses != best.addresses:
        out.append("ADR(differs)")
    for f in ("bday", "anniversary", "note", "gender"):
        if getattr(other, f) and getattr(other, f) != getattr(best, f):
            out.append(f.upper())
    if other.related:
        out.append(f"RELATED×{len(other.related)}")
    if other.kind == "self":
        out.append("KIND=self")
    if other.uid:
        out.append(f"UID {other.uid} (links to it will dangle)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=None)
    args = ap.parse_args()

    files = collect_merge_sources(ROOT / "cards-in")
    if not files:
        print("No .vcf files in cards-in/ — nothing to simulate.")
        return 0

    region = args.region
    if not region:
        region = "GB"
        conf = ROOT / "local" / "vcard.conf"
        if conf.exists():
            import tomllib
            try:
                region = tomllib.loads(conf.read_text(encoding="utf-8")).get("default_region", "GB")
            except Exception:
                pass

    # 1. Parse census — what the files contain vs what survives parsing
    props, begins = raw_property_census(files)
    pairs = read_vcards_from_files(files)
    print("== PARSE ==")
    for name, n in begins.items():
        print(f"  {name}: {n} BEGIN:VCARD")
    print(f"  parsed: {len(pairs)} of {sum(begins.values())}"
          + ("   <-- SOME CARDS SILENTLY SKIPPED" if len(pairs) < sum(begins.values()) else ""))

    dropped = {k: v for k, v in props.items() if k not in KEPT}
    print("\n== PROPERTIES THAT WILL NOT SURVIVE INTO MASTER ==")
    for k, v in sorted(dropped.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<28} {v}")
    if not dropped:
        print("  (none)")

    # 2. Replicate /api/process in memory
    new_cards = normalize_cards(pairs)
    stripper = DefaultStripper(keep_unknown=False)
    new_cards = [stripper.strip(c) for c in new_cards]
    normalize_phones_in_cards(new_cards, default_region=region, infer_from_adr=True)
    classify_entities(new_cards)
    auto_tag_categories(new_cards)

    master_vcf = ROOT / "cards-master" / "master.vcf"
    existing = normalize_cards(read_vcards_from_files([master_vcf])) if master_vcf.exists() else []
    print(f"\n== MASTER == {len(existing)} existing cards")

    merged, added, updated = merge_import_into_master(new_cards, existing)
    print(f"  merge_import_into_master: +{added} added, {updated} REPLACED wholesale")
    for i, c in enumerate(existing):
        if merged[i] is not c:
            print(f"    REPLACED: {label(c)}  (existing edits/categories/RELATED on this card are discarded)")

    clusters = [cl for cl in find_duplicate_clusters(merged) if len(cl) > 1]
    print(f"\n== AUTO-MERGE CLUSTERS (threshold 70) == {len(clusters)}")
    for cl in clusters:
        best = max(cl, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
        print(f"  KEEP  {label(best)}")
        for o in cl:
            if o is best:
                continue
            lf = lost_fields(best, o)
            print(f"   ← {label(o)}" + (f"   LOSES: {', '.join(lf)}" if lf else ""))

    total = len(merged) - sum(len(cl) - 1 for cl in clusters)
    print(f"\nResult would be {total} cards (from {len(existing)} + {len(new_cards)} imported).")
    print("Nothing has been written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
