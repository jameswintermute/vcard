"""Printing helpers for vCard Studio.

Keeps label/address-book rendering out of the HTTP request handler.  The
functions here are deliberately side-effect free except for the two generators,
which write HTML files below the supplied print directory.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any


_COUPLE_TYPES = frozenset({
    "spouse", "partner", "husband", "wife",
    "co-habitant", "cohabitant", "domestic partner",
})
_MALE_PREFIXES = {"mr", "master", "sir", "lord"}
_FEMALE_PREFIXES = {"mrs", "ms", "miss", "lady", "dame"}
_KNOWN_PREFIXES = {
    "mr", "mrs", "ms", "miss", "dr", "prof", "rev",
    "capt", "maj", "col", "lt", "sgt", "cpl", "master", "sir",
    "lord", "lady", "dame",
}
_UK_COUNTRIES = {
    "uk", "united kingdom", "england", "scotland", "wales", "gb",
    "great britain", "northern ireland",
}


def esc_html(value: Any) -> str:
    return (str(value) if value is not None else "").replace(
        "&", "&amp;"
    ).replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _name(card):
    return getattr(card, "name", None)


def _prefix(card) -> str:
    n = _name(card)
    if n and getattr(n, "prefix", None):
        return n.prefix.strip()
    gender = (getattr(card, "gender", None) or "").upper()
    if gender == "M":
        return "Mr"
    if gender == "F":
        return "Mrs"
    return ""


def _given(card) -> str:
    n = _name(card)
    if n and getattr(n, "given", None):
        return n.given.strip()
    fn = (getattr(card, "fn", None) or "").strip()
    return fn.split()[0] if fn else ""


def _family(card) -> str:
    n = _name(card)
    if n and getattr(n, "family", None):
        return n.family.strip()
    fn = (getattr(card, "fn", None) or "").strip()
    bits = fn.split()
    return bits[-1] if len(bits) > 1 else ""


def _initial(card) -> str:
    g = _given(card)
    return g[0].upper() if g else ""


def _is_male(card) -> bool:
    gender = (getattr(card, "gender", None) or "").upper()
    if gender == "M":
        return True
    if gender == "F":
        return False
    return _prefix(card).lower().rstrip(".") in _MALE_PREFIXES


def _is_female(card) -> bool:
    gender = (getattr(card, "gender", None) or "").upper()
    if gender == "F":
        return True
    if gender == "M":
        return False
    return _prefix(card).lower().rstrip(".") in _FEMALE_PREFIXES


def _format_single(card) -> str:
    fn = (getattr(card, "fn", None) or getattr(card, "org", None) or "Unknown").strip()
    n = _name(card)
    if getattr(card, "kind", None) == "org" or not n or (not _family(card) and not _given(card)):
        return fn
    p = _prefix(card)
    return f"{p} {fn}".strip() if p and not fn.lower().startswith(p.lower()) else fn


def _preferred_address(card):
    """Choose the best usable postal address without assuming addresses[0]."""
    addresses = list(getattr(card, "addresses", None) or [])
    usable = [a for a in addresses if any(
        (getattr(a, field, None) or "").strip()
        for field in ("street", "extended", "locality", "region", "postal_code")
    )]
    if not usable:
        return None
    for addr in usable:
        if bool(getattr(addr, "pref", False)):
            return addr
    # HOME is a useful default for address labels if no address is explicitly preferred.
    for addr in usable:
        if (getattr(addr, "type", None) or "").upper() == "HOME":
            return addr
    return usable[0]


def _addr_key(card):
    a = _preferred_address(card)
    if not a:
        return None
    street = re.sub(r"\s+", " ", (getattr(a, "street", None) or "").strip().lower())
    postcode = re.sub(r"\s+", "", (getattr(a, "postal_code", None) or "").strip().lower())
    return (street, postcode) if street or postcode else None


def _format_address(card, include_country: bool) -> list[str]:
    a = _preferred_address(card)
    if not a:
        return []
    lines: list[str] = []
    for field in ("street", "extended", "locality", "region", "postal_code"):
        value = (getattr(a, field, None) or "").strip()
        if value:
            lines.append(value)
    country = (getattr(a, "country", None) or "").strip()
    if include_country and country and country.lower() not in _UK_COUNTRIES:
        lines.append(country)
    return lines


def _format_couple(c1, c2, style: str) -> str:
    fam = _family(c1) or _family(c2)
    same_sex = (_is_male(c1) and _is_male(c2)) or (_is_female(c1) and _is_female(c2))

    if same_sex:
        a, b = (c1, c2) if (_given(c1) or "") <= (_given(c2) or "") else (c2, c1)
        pa, pb = _prefix(a), _prefix(b)
        if style == "informal":
            return f"{_given(a)} & {_given(b)} {fam}".strip()
        if style == "family":
            return f"The {fam} Family".strip()
        if style == "formal_no_initial":
            return f"{pa or _initial(a)} & {pb or _initial(b)} {fam}".strip()
        if pa and pb:
            return f"{pa} {_initial(a)} & {pb} {_initial(b)} {fam}".strip()
        return f"{_initial(a)} & {_initial(b)} {fam}".strip()

    male = c1 if _is_male(c1) else (c2 if _is_male(c2) else c1)
    female = c2 if male is c1 else c1
    pm, pf = _prefix(male), _prefix(female)

    if style == "informal":
        return f"{_given(male)} & {_given(female)} {fam}".strip()
    if style == "family":
        return f"The {fam} Family".strip()
    if style == "formal_no_initial":
        if pm and pf:
            return f"{pm} & {pf} {fam}".strip()
        return f"{pm or pf} {fam}".strip()
    if style == "formal_both":
        if pm and pf:
            return f"{pm} {_initial(male)} & {pf} {_initial(female)} {fam}".strip()
        return f"{_initial(male)} & {_initial(female)} {fam}".strip()

    # british_formal default — e.g. Mr & Mrs J Smith
    if pm and pf:
        return f"{pm} & {pf} {_initial(male)} {fam}".strip()
    if pm:
        return f"{pm} {_initial(male)} {fam}".strip()
    if pf:
        return f"{pf} {_initial(female)} {fam}".strip()
    return f"{_initial(male)} & {_initial(female)} {fam}".strip()


def _format_couple_from_text(card, spouse_name: str, style: str) -> str:
    fam = _family(card)
    parts = spouse_name.strip().split()
    sp_prefix = ""
    if parts and parts[0].rstrip(".").lower() in _KNOWN_PREFIXES:
        sp_prefix = parts.pop(0)
    sp_given = parts[0] if parts else ""
    sp_initial = sp_given[:1].upper()

    card_male = _is_male(card)
    card_female = _is_female(card)
    sp_male = sp_prefix.rstrip(".").lower() in _MALE_PREFIXES if sp_prefix else False
    sp_female = sp_prefix.rstrip(".").lower() in _FEMALE_PREFIXES if sp_prefix else False
    same_sex = (card_male and sp_male) or (card_female and sp_female)

    if not sp_prefix and not same_sex and style not in {"informal", "family"}:
        if card_male:
            sp_prefix = "Mrs"
        elif card_female:
            sp_prefix = "Mr"

    if style == "informal":
        return f"{_given(card)} & {sp_given or spouse_name} {fam}".strip()
    if style == "family":
        return f"The {fam} Family".strip() if fam else spouse_name

    pc = _prefix(card)
    ci = _initial(card)
    if same_sex:
        if style == "formal_no_initial":
            return f"{pc} & {sp_prefix or pc} {fam}".strip()
        if pc and sp_prefix:
            if ci <= sp_initial:
                return f"{pc} {ci} & {sp_prefix} {sp_initial} {fam}".strip()
            return f"{sp_prefix} {sp_initial} & {pc} {ci} {fam}".strip()
        return f"{_format_single(card)} & {spouse_name}".strip()

    if style == "formal_no_initial":
        if pc and sp_prefix:
            pair = f"{pc} & {sp_prefix}" if card_male else f"{sp_prefix} & {pc}"
            return f"{pair} {fam}".strip()
        return f"{pc or sp_prefix} {fam}".strip()
    if style == "formal_both":
        if pc and sp_prefix:
            if card_male:
                return f"{pc} {ci} & {sp_prefix} {sp_initial} {fam}".strip()
            return f"{sp_prefix} {sp_initial} & {pc} {ci} {fam}".strip()
        return f"{_format_single(card)} & {spouse_name}".strip()

    if pc and sp_prefix:
        if card_male:
            return f"{pc} & {sp_prefix} {ci} {fam}".strip()
        return f"{sp_prefix} & {pc} {sp_initial} {fam}".strip()
    return f"{_format_single(card)} & {spouse_name}".strip()


def build_label_records(cards, category: str = "", style: str = "british_formal",
                        include_country: bool = True, indices: list[int] | None = None) -> list[dict]:
    """Build postal-label records, merging eligible couples at one address."""
    uid_map = {c.uid: c for c in cards if getattr(c, "uid", None)}
    if indices is not None:
        pool = [cards[i] for i in indices if isinstance(i, int) and 0 <= i < len(cards)]
    elif category:
        pool = [c for c in cards if category in (getattr(c, "categories", None) or [])]
    else:
        pool = [c for c in cards if getattr(c, "kind", None) != "self"]
    pool = [c for c in pool if _preferred_address(c)]
    pool_by_uid = {c.uid: c for c in pool if getattr(c, "uid", None)}

    used: set[str] = set()
    records: list[dict] = []
    for card in pool:
        uid = getattr(card, "uid", None)
        if uid and uid in used:
            continue

        partner = None
        partner_text = None
        if style != "individual":
            for rel in sorted(getattr(card, "related", None) or [],
                              key=lambda r: 0 if (getattr(r, "rel_type", "") or "").lower() in _COUPLE_TYPES else 1):
                if (getattr(rel, "rel_type", "") or "").lower().strip() not in _COUPLE_TYPES:
                    continue
                rel_uid = getattr(rel, "uid", None)
                if rel_uid:
                    candidate = pool_by_uid.get(rel_uid) or uid_map.get(rel_uid)
                    if not candidate:
                        continue
                    candidate_uid = getattr(candidate, "uid", None)
                    if candidate_uid and candidate_uid in used:
                        continue
                    if _family(card) and _family(card).lower() == _family(candidate).lower():
                        if _addr_key(card) and _addr_key(card) == _addr_key(candidate):
                            partner = candidate
                            break
                elif getattr(rel, "text", None):
                    partner_text = rel.text.strip()
                    if partner_text:
                        break

        if partner is not None:
            if uid:
                used.add(uid)
            if getattr(partner, "uid", None):
                used.add(partner.uid)
            records.append({
                "name": _format_couple(card, partner, style),
                "address": _format_address(card, include_country),
                "merged": True,
            })
        elif partner_text:
            if uid:
                used.add(uid)
            records.append({
                "name": _format_couple_from_text(card, partner_text, style),
                "address": _format_address(card, include_country),
                "merged": True,
            })
        else:
            if uid:
                used.add(uid)
            records.append({
                "name": _format_single(card),
                "address": _format_address(card, include_country),
                "merged": False,
            })

    records.sort(key=lambda r: ((r["name"].split()[-1] if r["name"].split() else "").lower(), r["name"].lower()))
    return records


def preview_labels(cards, body: dict) -> dict:
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    category = body.get("category", "")
    if category:
        pool_all = [c for c in cards if category in (getattr(c, "categories", None) or [])]
    else:
        pool_all = [c for c in cards if getattr(c, "kind", None) != "self"]

    no_address = []
    for i, c in enumerate(cards):
        if c not in pool_all or _preferred_address(c):
            continue
        no_address.append({"fn": c.fn or c.org or "Unknown", "_idx": i})
    no_address.sort(key=lambda r: r["fn"].lower())

    indices = body.get("indices")
    if indices is not None:
        indices = [int(i) for i in indices]
    records = build_label_records(
        cards,
        category=category,
        style=body.get("style", "british_formal"),
        include_country=bool(body.get("include_country", True)),
        indices=indices,
    )
    return {
        "ok": True,
        "records": records,
        "total": len(records),
        "merged": sum(1 for r in records if r["merged"]),
        "no_address": no_address,
    }


def label_options(cards, body: dict) -> dict:
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    style = body.get("style", "british_formal")
    uid_map = {c.uid: (i, c) for i, c in enumerate(cards) if getattr(c, "uid", None)}
    results = []
    for raw_idx in body.get("indices", []):
        idx = int(raw_idx)
        if not 0 <= idx < len(cards):
            continue
        card = cards[idx]
        couple_name = None
        couple_idx = None
        card_key = _addr_key(card)
        for rel in getattr(card, "related", None) or []:
            if (getattr(rel, "rel_type", "") or "").lower().strip() not in _COUPLE_TYPES:
                continue
            if getattr(rel, "uid", None) and rel.uid in uid_map:
                pi, partner = uid_map[rel.uid]
                if card_key and card_key == _addr_key(partner):
                    couple_name = _format_couple(card, partner, style)
                    couple_idx = pi
                    break
            if getattr(rel, "text", None):
                couple_name = _format_couple_from_text(card, rel.text.strip(), style)
                break
        results.append({
            "_idx": idx,
            "fn": card.fn or card.org or "Unknown",
            "single_name": _format_single(card),
            "couple_name": couple_name,
            "couple_idx": couple_idx,
        })
    return {"ok": True, "options": results}


def print_modules() -> dict:
    from .print_modules import get_all_modules
    try:
        modules = get_all_modules()
        return {"ok": True, "modules": modules}
    except Exception as exc:
        return {"ok": False, "modules": [], "error": str(exc)}


def generate_labels(cards, print_dir: Path, body: dict) -> dict:
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    from .print_modules import get_all_modules, get_profile

    category = body.get("category", "")
    style = body.get("style", "british_formal")
    printer_id = body.get("printer_id", "")
    profile_id = body.get("profile_id", "")
    test_mode = bool(body.get("test_mode", False))
    include_country = bool(body.get("include_country", True))

    profile = get_profile(printer_id, profile_id) if printer_id and profile_id else None
    if not profile:
        modules = get_all_modules()
        if not modules:
            return {"ok": False, "error": "No print modules found"}
        module = modules[0]
        printer_id = module["printer_id"]
        profile_id = module["default_profile"]
        profile = get_profile(printer_id, profile_id)
    if not profile:
        return {"ok": False, "error": "Could not resolve print profile"}

    indices = body.get("indices")
    if indices is not None:
        indices = [int(i) for i in indices]
    records = build_label_records(cards, category, style, include_country, indices)
    if test_mode:
        records = records[:3]

    label_html = []
    for r in records:
        addr = "".join(f"<div class='aline'>{esc_html(line)}</div>" for line in r["address"])
        mark = " <span class='mmark'>⚭</span>" if r["merged"] else ""
        label_html.append(
            f"<div class='label'><div class='name'>{esc_html(r['name'])}{mark}</div>"
            f"<div class='addr'>{addr}</div></div>"
        )

    total = len(records)
    merged = sum(1 for r in records if r["merged"])
    test_banner = (
        "<div class='test-banner'>⚠ TEST MODE — first 3 labels only</div>"
        if test_mode else ""
    )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    cat_label = category or "all contacts"
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Address Labels — {esc_html(cat_label)}</title>
<style>
@page {{ {profile['page_css']} }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:Arial,Helvetica,sans-serif; background:white; }}
.label {{ {profile['label_css']} display:flex; flex-direction:column; justify-content:center; page-break-after:always; break-after:page; padding:1mm; }}
.name {{ font-size:{profile['name_size']}; font-weight:bold; color:#000; margin-bottom:1.5mm; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.addr {{ color:#111; }} .aline {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.mmark {{ font-size:7pt; color:#555; font-weight:normal; }}
.test-banner {{ background:#ff0; color:#000; text-align:center; font:10pt sans-serif; padding:4px; }}
.screen-header {{ text-align:center; font:11px monospace; color:#555; margin:10px auto 16px; padding:8px; max-width:750px; background:#fff; border:1px solid #ddd; }}
@media screen {{ body {{ background:#eee; padding:10px; }} .label {{ background:#fff; border:1px solid #bbb; border-radius:3px; margin:8px auto; box-shadow:0 1px 4px rgba(0,0,0,.15); padding:4mm 5mm; }} }}
@media print {{ .screen-header,.test-banner {{ display:none; }} body {{ background:white; }} }}
</style></head><body>{test_banner}
<div class="screen-header"><strong>vCard Studio — Address Labels</strong><br>
Category: <strong>{esc_html(cat_label)}</strong> · {total} label{'s' if total != 1 else ''} · {merged} couple{'s' if merged != 1 else ''} merged<br>
Printer profile: <strong>{esc_html(printer_id)} / {esc_html(profile_id)}</strong> · Generated {generated}<br>
<strong>Print:</strong> Ctrl+P / ⌘P · {esc_html(profile.get('hint', ''))}</div>
{''.join(label_html)}</body></html>"""

    print_dir.mkdir(parents=True, exist_ok=True)
    safe_cat = re.sub(r"[^\w-]", "-", category or "all").strip("-") or "all"
    suffix = "-TEST" if test_mode else ""
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = print_dir / f"labels-{safe_cat}-{stamp}{suffix}.html"
    out.write_text(html, encoding="utf-8")
    return {
        "ok": True, "file": str(out), "filename": out.name,
        "total": total, "merged": merged, "test_mode": test_mode,
    }


def generate_address_book(cards, print_dir: Path, params: dict, fmt_tel=None) -> dict:
    """Generate the printable address-book view used by the Print panel."""
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    fmt_tel = fmt_tel or (lambda x: x)
    get = lambda key, default="": params.get(key, [default])[0]
    category = get("category")
    paper = get("paper", "A5")
    incl_email = get("email", "1") == "1"
    incl_phone = get("phone", "1") == "1"
    incl_addr = get("address", "1") == "1"
    incl_org = get("org", "1") == "1"
    incl_note = get("note", "0") == "1"
    incl_rels = get("rels", "1") == "1"
    incl_cats = get("cats", "1") == "1"

    pool = [c for c in cards if category in (c.categories or [])] if category else list(cards)
    pool = [c for c in pool if getattr(c, "kind", None) != "self"]
    pool.sort(key=lambda c: (_family(c).lower(), _given(c).lower(), (c.fn or c.org or "").lower()))
    uid_names = {c.uid: c.fn or c.org or c.uid for c in cards if getattr(c, "uid", None)}

    def render_card(c):
        rows = [f"<div class='cn'>{esc_html(_format_single(c))}</div>"]
        if incl_org and c.org and c.kind != "org":
            text = esc_html(c.org) + (f" · {esc_html(c.title)}" if c.title else "")
            rows.append(f"<div class='cd org'>{text}</div>")
        if incl_rels:
            for rel in c.related or []:
                name = uid_names.get(rel.uid, rel.text or "") if rel.uid else (rel.text or "")
                if name:
                    rows.append(f"<div class='cd rel'>{esc_html((rel.rel_type or 'related').capitalize())}: {esc_html(name)}</div>")
        if incl_addr:
            lines = _format_address(c, True)
            if lines:
                rows.append(f"<div class='cd adr'>{esc_html(', '.join(lines))}</div>")
        if incl_phone:
            rows.extend(f"<div class='cd ph'>{esc_html(fmt_tel(t))}</div>" for t in (c.tels or [])[:2])
        if incl_email:
            rows.extend(f"<div class='cd em'>{esc_html(e)}</div>" for e in (c.emails or [])[:2])
        if incl_cats and c.categories:
            rows.append(f"<div class='cd cats'>{esc_html(', '.join(sorted(c.categories)))}</div>")
        if incl_note and c.note:
            note = re.sub(r"\s*\[vCS:(?:[^\[\]]|\[[^\[\]]*\])*\]", "", c.note).strip()
            if note:
                rows.append(f"<div class='cd note'>{esc_html(note)}</div>")
        return "<section class='card'>" + "".join(rows) + "</section>"

    paper_css = {"A4": "A4 portrait", "Letter": "letter portrait", "A5": "A5 portrait"}.get(paper, "A5 portrait")
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>vCard Studio Address Book</title>
<style>
@page {{ size:{paper_css}; margin:12mm 14mm; }}
body {{ font-family:Arial,Helvetica,sans-serif; font-size:8.5pt; color:#111; }}
h1 {{ font-size:16pt; margin:0 0 3mm; }} .meta {{ color:#666; margin-bottom:6mm; }}
.grid {{ columns:2; column-gap:8mm; }} .card {{ break-inside:avoid; border-bottom:.4pt solid #ddd; padding:2.5mm 0; }}
.cn {{ font-weight:bold; font-size:9pt; margin-bottom:1mm; }} .cd {{ margin-top:.5mm; }} .org,.note,.cats {{ color:#666; }} .ph,.em {{ color:#174f7a; }}
@media screen {{ body {{ max-width:800px; margin:20px auto; padding:25px; box-shadow:0 1px 6px #999; }} }}
</style></head><body><h1>Address Book</h1><div class='meta'>{len(pool)} contacts · generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<div class='grid'>{''.join(render_card(c) for c in pool)}</div></body></html>"""
    print_dir.mkdir(parents=True, exist_ok=True)
    safe_cat = re.sub(r"[^\w-]", "-", category or "all").strip("-") or "all"
    out = print_dir / f"addressbook-{safe_cat}-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.html"
    out.write_text(html, encoding="utf-8")
    return {"ok": True, "filename": out.name, "count": len(pool)}
