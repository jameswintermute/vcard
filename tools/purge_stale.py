#!/usr/bin/env python3
"""
purge_stale.py — find, and optionally remove, stale data in the vCard Studio master.

DRY RUN by default: prints what it would change and writes a report; changes nothing.

    # report only (safe, any time):
    PYTHONPATH=src .venv/bin/python tools/purge_stale.py

    # audit an exported .vcf instead of the master (read-only):
    PYTHONPATH=src .venv/bin/python tools/purge_stale.py --file cards-out/some-export.vcf

    # apply (stop the vCard Studio server first):
    PYTHONPATH=src .venv/bin/python tools/purge_stale.py --apply

Fixed automatically with --apply:
  R1  Hidden duplicate addresses: on one contact, several addresses with the same
      postcode (or, without a postcode, the same street) are versions of one place.
      The FIRST one (the one the edit form shows and saves) is kept; later copies
      are removed. Addresses with a different postcode are kept.
  R2  Stale Apple country codes: the stored code is reset to match the visible
      country name (or cleared when the name is not recognised).

Reported only (needs your judgement):
  - Street lines that look joined ("Ash BarnTerrys Lodge Road")
  - Contacts that still have more than one distinct place
  - Contacts sharing an identical display name (possible duplicate cards)

--apply copies cards-master/ to var/backups/cards-master-<timestamp>/ first
(var/ is git-ignored), then saves through vCard Studio's own save_master().
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import socket
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from vcard_normalizer.countries import country_code_for       # noqa: E402
from vcard_normalizer.io import read_vcards_from_files        # noqa: E402
from vcard_normalizer.master import load_master, save_master  # noqa: E402
from vcard_normalizer.normalize import normalize_cards        # noqa: E402

PORT = 8421
JOINED = re.compile(r"[a-z\)][A-Z][a-z]")   # lower-case letter running straight into a capitalised word


def _place_key(a) -> str | None:
    pc = re.sub(r"\s+", "", a.postal_code or "").casefold()
    if pc:
        return "pc:" + pc
    st = re.sub(r"\s+", " ", (a.street or "").strip()).casefold()
    return "st:" + st if st else None


def _addr_text(a) -> str:
    parts = [a.extended, a.street, a.po_box, a.locality, a.region, a.postal_code, a.country]
    return ", ".join(p.replace("\n", " / ").strip() for p in parts if p and p.strip())


def _name(c) -> str:
    return (c.fn or "").strip() or "(no name)"


def analyse(cards):
    """Return a plan: per-card R1/R2 fixes plus report-only findings. Pure — mutates nothing."""
    plan = {"r1": [], "r2": [], "joined": [], "multi_place": [], "same_name": []}
    for i, c in enumerate(cards):
        groups: dict[str, list[int]] = defaultdict(list)
        for j, a in enumerate(c.addresses or []):
            k = _place_key(a)
            if k:
                groups[k].append(j)
        drop = sorted(j for idxs in groups.values() for j in idxs[1:])
        if drop:
            plan["r1"].append((i, drop))
        if len(groups) > 1:
            plan["multi_place"].append(i)
        for j, a in enumerate(c.addresses or []):
            if j in drop:
                continue
            want = country_code_for(a.country) if (a.country or "").strip() else (a.apple_country_code or "")
            have = (a.apple_country_code or "").strip().lower()
            if have and want != have:
                plan["r2"].append((i, j, have, want))
            for line in (a.street or "").splitlines():
                if JOINED.search(line):
                    plan["joined"].append((i, j, line))
    by_name: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cards):
        n = re.sub(r"\s+", " ", (c.fn or "").strip()).casefold()
        if n:
            by_name[n].append(i)
    plan["same_name"] = [idxs for idxs in by_name.values() if len(idxs) > 1]
    return plan


def apply(cards, plan) -> int:
    """Apply R1 and R2 in place. Returns the number of contacts changed."""
    changed = set()
    for i, j, _have, want in plan["r2"]:
        cards[i].addresses[j].apple_country_code = want
        changed.add(i)
    for i, drop in plan["r1"]:
        cards[i].addresses = [a for j, a in enumerate(cards[i].addresses) if j not in set(drop)]
        changed.add(i)
    return len(changed)


def report(cards, plan, out: Path, source: str) -> None:
    e = html.escape
    rows = [f"<!doctype html><meta charset=utf-8><title>Stale data audit</title>"
            "<style>body{font:13px/1.45 system-ui,sans-serif;margin:24px;max-width:1100px}"
            "h2{font-size:16px;border-bottom:1px solid #ccc;margin-top:24px}td,th{border-bottom:1px solid #eee;"
            "padding:3px 6px;text-align:left;vertical-align:top}table{border-collapse:collapse;width:100%}"
            ".x{color:#a00;text-decoration:line-through}.dim{color:#666}</style>",
            f"<h1>Stale data audit</h1><p class=dim>{e(source)} · {len(cards)} contacts · "
            f"{datetime.now():%Y-%m-%d %H:%M}</p>"]
    rows.append(f"<h2>R1 · Hidden duplicate addresses removed ({sum(len(d) for _, d in plan['r1'])} on "
                f"{len(plan['r1'])} contacts)</h2><table><tr><th>Contact</th><th>Kept</th><th>Removed</th></tr>")
    for i, drop in plan["r1"]:
        c = cards[i]
        keep = [a for j, a in enumerate(c.addresses) if j not in drop]
        rows.append(f"<tr><td>{e(_name(c))}</td><td>{'<br>'.join(e(_addr_text(a)) for a in keep)}</td>"
                    f"<td class=x>{'<br>'.join(e(_addr_text(c.addresses[j])) for j in drop)}</td></tr>")
    rows.append("</table>")
    rows.append(f"<h2>R2 · Stale Apple country codes reset ({len(plan['r2'])})</h2><table>"
                "<tr><th>Contact</th><th>Country shown</th><th>Stored code</th><th>New code</th></tr>")
    for i, j, have, want in plan["r2"]:
        rows.append(f"<tr><td>{e(_name(cards[i]))}</td><td>{e(cards[i].addresses[j].country or '')}</td>"
                    f"<td class=x>{e(have)}</td><td>{e(want) or '<span class=dim>(none)</span>'}</td></tr>")
    rows.append("</table>")
    rows.append(f"<h2>Report only · street lines that look joined ({len(plan['joined'])})</h2><table>")
    for i, _j, line in plan["joined"]:
        rows.append(f"<tr><td>{e(_name(cards[i]))}</td><td>{e(line)}</td></tr>")
    rows.append("</table>")
    rows.append(f"<h2>Report only · contacts with more than one place ({len(plan['multi_place'])})</h2><table>")
    for i in plan["multi_place"]:
        rows.append(f"<tr><td>{e(_name(cards[i]))}</td><td>"
                    f"{'<br>'.join(e(_addr_text(a)) for a in cards[i].addresses)}</td></tr>")
    rows.append("</table>")
    rows.append(f"<h2>Report only · identical display names ({len(plan['same_name'])})</h2><p>"
                + e(" · ".join(f"{_name(cards[g[0]])} ×{len(g)}" for g in plan["same_name"])) + "</p>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows), encoding="utf-8")


def _server_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--file", help="audit this .vcf instead of the master (always read-only)")
    ap.add_argument("--apply", action="store_true", help="apply R1/R2 to the master (backup first)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    if a.file:
        if a.apply:
            sys.exit("--apply only works on the master, not on --file.")
        cards = normalize_cards(read_vcards_from_files([Path(a.file)]))
        source = Path(a.file).name
    else:
        loaded = load_master(root)
        if not loaded:
            sys.exit(f"No master found under {root}/cards-master — run from the vCard Studio folder.")
        cards, meta = loaded
        source = "cards-master/master.vcf"

    plan = analyse(cards)
    stamp = f"{datetime.now():%Y-%m-%d-%H%M%S}"
    out = Path(a.out) if a.out else root / "print" / f"stale-audit-{stamp}.html"
    report(cards, plan, out, source)

    print(f"Audited {len(cards)} contacts from {source}")
    print(f"  R1 hidden duplicate addresses : {sum(len(d) for _, d in plan['r1'])} on {len(plan['r1'])} contacts")
    print(f"  R2 stale Apple country codes  : {len(plan['r2'])}")
    print(f"  joined-looking street lines   : {len(plan['joined'])}   (report only)")
    print(f"  contacts with >1 place        : {len(plan['multi_place'])}   (report only)")
    print(f"  identical display names       : {len(plan['same_name'])}   (report only)")
    print(f"Report: {out}")

    if not a.apply:
        print("\nDry run — nothing changed. Re-run with --apply (server stopped) to fix R1 and R2.")
        return 0
    if _server_running():
        print(f"\nRefusing to apply: vCard Studio is running on port {PORT}. Stop it (Ctrl+C) and re-run.")
        return 2
    if not plan["r1"] and not plan["r2"]:
        print("\nNothing to apply.")
        return 0
    backup = root / "var" / "backups" / f"cards-master-{stamp}"
    shutil.copytree(root / "cards-master", backup)
    n = apply(cards, plan)
    save_master(cards, root=root, source_files=meta.get("source_files"),
                input_count=meta.get("input_count", len(cards)),
                duplicate_clusters=meta.get("duplicate_clusters", 0), changed_indices=None)
    print(f"\nApplied: {n} contacts updated. Backup: {backup}")
    print(f"To undo: stop the server, then  rm -rf cards-master && cp -r {backup} cards-master")
    return 0


if __name__ == "__main__":
    sys.exit(main())
