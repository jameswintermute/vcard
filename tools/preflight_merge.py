#!/usr/bin/env python3
"""preflight_merge.py — READ-ONLY dry run of a vCard Studio import.

Runs the real /api/process pipeline in memory against the files in cards-in/
and the current cards-master/master.vcf, and reports:

  1. cards the parser silently skipped
  2. vCard properties that do not survive a round-trip through the model
  3. every incoming card that would be folded into an existing card, flagging
     name mismatches (e.g. two people sharing a landline or family email) and
     incoming values discarded because the master value wins
  4. duplicate clusters the post-import dedupe pass would auto-merge

It hooks the project's own merge function rather than re-implementing it, so
the report tracks whatever the code in src/ actually does.  Writes nothing,
moves nothing.

Usage (from the project root, using the app's venv):
    .venv/bin/python tools/preflight_merge.py
    .venv/bin/python tools/preflight_merge.py --region GB
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rapidfuzz import fuzz  # noqa: E402

import vcard_normalizer.master as master_mod  # noqa: E402
from vcard_normalizer.dedupe import find_duplicate_clusters  # noqa: E402
from vcard_normalizer.exporter import card_to_vcf_text  # noqa: E402
from vcard_normalizer.formatters import (  # noqa: E402
    auto_tag_categories, classify_entities, normalize_phones_in_cards,
)
from vcard_normalizer.io import collect_merge_sources, read_vcards_from_files  # noqa: E402
from vcard_normalizer.normalize import normalize_cards  # noqa: E402
from vcard_normalizer.proprietary import DefaultStripper  # noqa: E402

SCALARS = ("fn", "org", "title", "bday", "anniversary", "gender", "kind", "note")
NAME_MATCH_THRESHOLD = 85
_PROP_LINE = re.compile(r"^([A-Za-z0-9-]+)[;:]")


def label(c) -> str:
    return c.fn or c.org or c.uid or "?"


def raw_names(vc) -> set[str]:
    names = set()
    for child in vc.getChildren():
        n = getattr(child, "name", "") or ""
        n = n.upper().split(".")[-1]
        if n and n not in ("BEGIN", "END"):
            names.add(n)
    return names


def written_names(card) -> set[str]:
    names = set()
    for line in card_to_vcf_text(card).splitlines():
        m = _PROP_LINE.match(line)
        if m:
            names.add(m.group(1).upper())
    return names


def load_region(cli: str | None) -> str:
    if cli:
        return cli
    conf = ROOT / "local" / "vcard.conf"
    if conf.exists():
        try:
            return tomllib.loads(conf.read_text(encoding="utf-8")).get("default_region", "GB")
        except Exception:
            pass
    return "GB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=None)
    args = ap.parse_args()
    region = load_region(args.region)

    files = collect_merge_sources(ROOT / "cards-in")
    if not files:
        print("No .vcf files in cards-in/ — nothing to simulate.")
        return 0

    # ── 1. Parse census ──────────────────────────────────────────────────────
    begins = {f.name: len(re.findall(r"^BEGIN:VCARD", f.read_text(encoding="utf-8", errors="replace"),
                                     re.M | re.I)) for f in files}
    pairs = read_vcards_from_files(files)
    total_begins = sum(begins.values())
    print("== 1. PARSE ==")
    for name, n in begins.items():
        print(f"  {name}: {n} BEGIN:VCARD")
    flag = "   <-- SOME CARDS SILENTLY SKIPPED" if len(pairs) < total_begins else ""
    print(f"  parsed: {len(pairs)} of {total_begins}{flag}")

    raw_sets = [raw_names(vc) for vc, _ in pairs]

    # ── Replicate /api/process up to the master merge ───────────────────────
    new_cards = normalize_cards(pairs)
    stripper = DefaultStripper(keep_unknown=False)
    new_cards = [stripper.strip(c) for c in new_cards]
    normalize_phones_in_cards(new_cards, default_region=region, infer_from_adr=True)
    classify_entities(new_cards)
    auto_tag_categories(new_cards)

    # ── 2. Round-trip property survival ─────────────────────────────────────
    lost: Counter = Counter()
    for before, card in zip(raw_sets, new_cards):
        for n in before - written_names(card):
            lost[n] += 1
    print("\n== 2. PROPERTIES THAT DO NOT SURVIVE INTO MASTER (cards affected) ==")
    if lost:
        for n, v in sorted(lost.items(), key=lambda kv: -kv[1]):
            print(f"  {n:<32} {v}")
    else:
        print("  (none)")

    master_vcf = ROOT / "cards-master" / "master.vcf"
    existing = normalize_cards(read_vcards_from_files([master_vcf])) if master_vcf.exists() else []
    existing_ids = {id(c) for c in existing}
    print(f"\n== MASTER == {len(existing)} existing cards")

    # ── 3. Hook the real merge function to observe every fold ───────────────
    folds: list[tuple[str, str, bool, bool, list[str]]] = []
    real_merge = master_mod.merge_cards_preserving_base

    def spy(base, incoming, *a, **kw):
        before = {f: getattr(base, f, None) for f in SCALARS}
        discarded = [f"{f.upper()}={getattr(incoming, f)!r}" for f in SCALARS
                     if getattr(incoming, f, None) and before[f]
                     and str(getattr(incoming, f)).strip().casefold() != str(before[f]).strip().casefold()]
        names_differ = bool(base.fn and incoming.fn and
                            fuzz.token_sort_ratio(base.fn, incoming.fn) < NAME_MATCH_THRESHOLD)
        folds.append((label(base), label(incoming), id(base) in existing_ids, names_differ, discarded))
        return real_merge(base, incoming, *a, **kw)

    master_mod.merge_cards_preserving_base = spy
    try:
        merged, added, updated = master_mod.merge_import_into_master(new_cards, existing)
    finally:
        master_mod.merge_cards_preserving_base = real_merge

    print(f"\n== 3. IMPORT MATCHING == +{added} new, {len(folds)} folded into another card")
    suspicious = [f for f in folds if f[3]]
    for base, inc, into_master, differ, discarded in folds:
        where = "master" if into_master else "same import batch"
        mark = "  <-- DIFFERENT NAMES: check this is one person" if differ else ""
        print(f"  {inc!s:<32} → {base} ({where}){mark}")
        if discarded:
            print(f"      incoming values discarded (master wins): {', '.join(discarded)}")
    if not folds:
        print("  (none)")

    # ── 4. Post-import dedupe clusters ──────────────────────────────────────
    clusters = [cl for cl in find_duplicate_clusters(merged) if len(cl) > 1]
    print(f"\n== 4. POST-IMPORT AUTO-MERGE CLUSTERS == {len(clusters)}")
    for cl in clusters:
        print("  " + "  +  ".join(label(c) for c in cl))

    total = len(merged) - sum(len(cl) - 1 for cl in clusters)
    print(f"\nResult would be {total} cards "
          f"(from {len(existing)} existing + {len(new_cards)} imported).")
    if suspicious:
        print(f"WARNING: {len(suspicious)} fold(s) join cards with different names.")
    print("Nothing has been written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
