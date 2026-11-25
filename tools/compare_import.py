#!/usr/bin/env python3
"""
compare_import.py — READ-ONLY comparison of a .vcf export (e.g. iPhone/iCloud)
against the vCard Studio master. Writes nothing to cards-master/ and does not
move the import file. The only output is a report file and a console summary.

Usage (from the project root):
    PYTHONPATH=src .venv/bin/python tools/compare_import.py cards-in/2026-11-25-1135-iCloud-import.vcf

Options:
    --root PATH      project root (default: current directory)
    --region CC      default phone region for numbers without +country (default GB)
    --out FILE       report path (default: print/compare-<timestamp>.html; print/ is git-ignored)

Matching mirrors Unify's additive merge (master.merge_import_into_master):
canonical/provider UID, then a unique exact email, then a unique phone number.
Contacts that only match by name are listed separately for you to judge.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from vcard_normalizer._similarity import _tel_key           # noqa: E402
from vcard_normalizer.formatters import normalize_phones_in_cards  # noqa: E402
from vcard_normalizer.io import read_vcards_from_files      # noqa: E402
from vcard_normalizer.master import load_master             # noqa: E402
from vcard_normalizer.normalize import normalize_cards      # noqa: E402
from vcard_normalizer.proprietary import DefaultStripper    # noqa: E402

SCALARS = [("org", "organisation"), ("title", "job title"), ("bday", "birthday"),
           ("anniversary", "anniversary"), ("note", "note")]


# ── keys ─────────────────────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _email_key(e: str) -> str:
    return (e or "").strip().casefold()


def _place_key(a) -> str | None:
    pc = re.sub(r"\s+", "", (a.postal_code or "")).casefold()
    if pc:
        return "pc:" + pc
    st = _norm(a.street)
    return "st:" + st if st else None


def _addr_text(a) -> str:
    parts = [a.extended, a.street, a.po_box, a.locality, a.region, a.postal_code, a.country]
    return ", ".join(p.replace("\n", ", ").strip() for p in parts if p and p.strip())


def _name(c) -> str:
    return (c.fn or "").strip() or "(no name)"


# ── matching (same order as Unify) ───────────────────────────────────────────

def _index(cards):
    uid, email, tel, name = {}, {}, {}, {}
    for i, c in enumerate(cards):
        for u in [c.uid, *(c.external_uids or [])]:
            if u:
                uid.setdefault(u, set()).add(i)
        for e in c.emails or []:
            if e:
                email.setdefault(_email_key(e), set()).add(i)
        for t in c.tels or []:
            k = _tel_key(t)
            if k:
                tel.setdefault(k, set()).add(i)
        n = _norm(c.fn)
        if n:
            name.setdefault(n, set()).add(i)
    return uid, email, tel, name


def _match(card, idx):
    """Return (master_index | None, how, ambiguous_candidates)."""
    uid, email, tel, name = idx
    steps = [
        ("UID", [u for u in [card.uid, *(card.external_uids or [])] if u], uid),
        ("email", [_email_key(e) for e in card.emails or [] if e], email),
        ("phone", [_tel_key(t) for t in card.tels or [] if _tel_key(t)], tel),
    ]
    ambiguous: set[int] = set()
    for how, keys, mapping in steps:
        if not keys:
            continue
        hits: set[int] = set()
        for k in keys:
            hits |= mapping.get(k, set())
        if len(hits) == 1:
            return next(iter(hits)), how, set()
        if len(hits) > 1:
            ambiguous |= hits
    hits = name.get(_norm(card.fn), set())
    if len(hits) == 1:
        return next(iter(hits)), "name only", ambiguous
    return None, "", ambiguous | hits


# ── per-contact differences (iPhone values the laptop lacks) ─────────────────

def _differences(imp, mas):
    diffs = []
    m_emails = {_email_key(e) for e in mas.emails or []}
    for e in imp.emails or []:
        if e and _email_key(e) not in m_emails:
            diffs.append(("email", e, ""))
    m_tels = {_tel_key(t) for t in mas.tels or [] if _tel_key(t)}
    for t in imp.tels or []:
        if _tel_key(t) and _tel_key(t) not in m_tels:
            diffs.append(("phone", t, ""))
    m_places = {_place_key(a): a for a in mas.addresses or [] if _place_key(a)}
    for a in imp.addresses or []:
        k = _place_key(a)
        if not k:
            continue
        if k not in m_places:
            diffs.append(("address (new place)", _addr_text(a), ""))
        elif _norm(_addr_text(a)) != _norm(_addr_text(m_places[k])):
            diffs.append(("address (same postcode, worded differently)",
                          _addr_text(a), _addr_text(m_places[k])))
    for attr, label in SCALARS:
        iv, mv = getattr(imp, attr, None), getattr(mas, attr, None)
        if iv and _norm(str(iv)) != _norm(str(mv)):
            diffs.append((label, str(iv), str(mv or "")))
    return diffs


# ── report ───────────────────────────────────────────────────────────────────

def _render(path, src, master_n, new, changed, name_only, ambiguous, laptop_only):
    e = html.escape
    css = ("body{font:13px/1.45 system-ui,sans-serif;margin:24px;max-width:1100px;color:#111}"
           "h1{font-size:20px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #ccc}"
           "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;"
           "padding:4px 6px;text-align:left;vertical-align:top}th{background:#f6f6f6}"
           ".dim{color:#666}.k{white-space:nowrap;color:#555}.note{background:#fff8e1;padding:8px 10px}")
    out = [f"<!doctype html><meta charset=utf-8><title>Import comparison</title><style>{css}</style>",
           f"<h1>Import comparison — read-only</h1><p class=dim>Import: {e(src)} · laptop master: "
           f"{master_n} contacts · generated {datetime.now():%Y-%m-%d %H:%M}</p>",
           "<p class=note>Nothing was changed. Values below are what the import has that the "
           "laptop does not. Apply what you want by hand in vCard Studio.</p>"]

    out.append(f"<h2>1 · New contacts — on the import, not on the laptop ({len(new)})</h2>")
    if new:
        out.append("<table><tr><th>Name</th><th>Emails</th><th>Phones</th><th>Address</th></tr>")
        for c in new:
            out.append(f"<tr><td>{e(_name(c))}</td><td>{e(', '.join(c.emails or []))}</td>"
                       f"<td>{e(', '.join(c.tels or []))}</td>"
                       f"<td>{e(' | '.join(_addr_text(a) for a in c.addresses or []))}</td></tr>")
        out.append("</table>")

    out.append(f"<h2>2 · Matched contacts with differences ({len(changed)})</h2>")
    for c, m, how, diffs in changed:
        out.append(f"<p><b>{e(_name(m))}</b> <span class=dim>(matched by {how}"
                   f"{'; import name: ' + e(_name(c)) if _norm(c.fn) != _norm(m.fn) else ''})</span></p>"
                   "<table><tr><th style='width:22%'>Field</th><th>On import</th><th>On laptop</th></tr>")
        for field, iv, mv in diffs:
            out.append(f"<tr><td class=k>{e(field)}</td><td>{e(iv)}</td><td class=dim>{e(mv) or '—'}</td></tr>")
        out.append("</table>")

    out.append(f"<h2>3 · Matched by name only — please check ({len(name_only)})</h2>"
               "<p class=dim>Same display name but no shared UID, email or phone. Unify would "
               "have added these as NEW contacts (possible duplicates).</p>")
    for c, m, diffs in name_only:
        out.append(f"<p><b>{e(_name(c))}</b></p><table><tr><th style='width:22%'>Field</th>"
                   "<th>On import</th><th>On laptop</th></tr>")
        for field, iv, mv in diffs or [("—", "no differing values", "")]:
            out.append(f"<tr><td class=k>{e(field)}</td><td>{e(iv)}</td><td class=dim>{e(mv) or '—'}</td></tr>")
        out.append("</table>")

    if ambiguous:
        out.append(f"<h2>4 · Ambiguous — matches several laptop contacts ({len(ambiguous)})</h2><table>"
                   "<tr><th>Import contact</th><th>Possible laptop matches</th></tr>")
        for c, cands in ambiguous:
            out.append(f"<tr><td>{e(_name(c))}</td><td>{e(' · '.join(cands))}</td></tr>")
        out.append("</table>")

    out.append(f"<h2>5 · Laptop-only — not on the import ({len(laptop_only)})</h2>"
               "<p class=dim>For information: contacts added or kept on the laptop only.</p><p>"
               + e(" · ".join(laptop_only)) + "</p>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("import_vcf")
    ap.add_argument("--root", default=".")
    ap.add_argument("--region", default="GB")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    src = Path(a.import_vcf).resolve()
    loaded = load_master(root)
    if not loaded:
        sys.exit(f"No master found under {root}/cards-master — run from the vCard Studio folder.")
    master, _meta = loaded

    imported = normalize_cards(read_vcards_from_files([src]))
    stripper = DefaultStripper(keep_unknown=False)
    imported = [stripper.strip(c) for c in imported]
    normalize_phones_in_cards(imported, default_region=a.region, infer_from_adr=True)

    idx = _index(master)
    matched_master: set[int] = set()
    new, changed, name_only, ambiguous = [], [], [], []
    for c in imported:
        i, how, cands = _match(c, idx)
        if i is None:
            if cands:
                ambiguous.append((c, sorted(_name(master[j]) for j in cands)))
            else:
                new.append(c)
            continue
        matched_master.add(i)
        diffs = _differences(c, master[i])
        if how == "name only":
            name_only.append((c, master[i], diffs))
        elif diffs:
            changed.append((c, master[i], how, diffs))

    laptop_only = sorted(_name(m) for j, m in enumerate(master) if j not in matched_master)
    out = Path(a.out) if a.out else root / "print" / f"compare-{datetime.now():%Y-%m-%d-%H%M%S}.html"
    _render(out, src.name, len(master), sorted(new, key=_name), changed, name_only, ambiguous, laptop_only)

    same = len(imported) - len(new) - len(changed) - len(name_only) - len(ambiguous)
    print(f"Import: {len(imported)} contacts · laptop master: {len(master)} (nothing was changed)")
    print(f"  new on import            : {len(new)}")
    print(f"  matched, with differences: {len(changed)}")
    print(f"  matched, identical       : {same}")
    print(f"  matched by name only     : {len(name_only)}  (check — Unify would add these as new)")
    print(f"  ambiguous                : {len(ambiguous)}")
    print(f"  laptop-only              : {len(laptop_only)}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
