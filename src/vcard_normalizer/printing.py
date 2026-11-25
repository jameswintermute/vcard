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


def _usable_addresses(card) -> list:
    return [a for a in (getattr(card, "addresses", None) or []) if any(
        (getattr(a, field, None) or "").strip()
        for field in ("street", "extended", "locality", "region", "postal_code")
    )]


def _place_key(a):
    """Identity of a physical place, for spotting stale versions of one address
    on the same card (e.g. a corrupted country, or a street mangled by an old
    merge such as "Send Hill HouseSend Hill").

    On one contact, a shared postcode is the strongest signal, so the postcode
    alone decides when present; the street is used only when there is no
    postcode. Two genuinely different homes of one person (e.g. UK and abroad)
    have different postcodes and stay distinct.
    """
    postcode = re.sub(r"\s+", "", (getattr(a, "postal_code", None) or "").strip().lower())
    if postcode:
        return ("pc", postcode)
    street = re.sub(r"\s+", " ", (getattr(a, "street", None) or "").strip().lower())
    return ("st", street) if street else None


def _preferred_address(card):
    """Choose the best usable postal address without assuming addresses[0].

    Order: PREF, then HOME, then the first usable address. Exception: the edit
    modal edits addresses[0]; if the chosen address is another *version of the
    same place* (same street + postcode), the edited addresses[0] wins, so a
    correction made in the UI is never overridden by a stale hidden duplicate.
    """
    addresses = list(getattr(card, "addresses", None) or [])
    usable = _usable_addresses(card)
    if not usable:
        return None
    chosen = None
    for addr in usable:
        if bool(getattr(addr, "pref", False)):
            chosen = addr
            break
    if chosen is None:
        # HOME is a useful default for address labels if no address is explicitly preferred.
        for addr in usable:
            if (getattr(addr, "type", None) or "").upper() == "HOME":
                chosen = addr
                break
    if chosen is None:
        chosen = usable[0]
    first = addresses[0] if addresses else None
    if (first is not None and chosen is not first and first in usable
            and _place_key(first) and _place_key(first) == _place_key(chosen)):
        return first
    return chosen


def _address_note(card) -> str | None:
    """Explain when the label address is not the one shown in the edit modal."""
    addresses = list(getattr(card, "addresses", None) or [])
    chosen = _preferred_address(card)
    if not addresses or chosen is None or chosen is addresses[0]:
        return None
    n = addresses.index(chosen) + 1
    kind = (getattr(chosen, "type", "") or "").upper() or "untyped"
    why = "marked preferred" if getattr(chosen, "pref", False) else f"{kind} address"
    return (f"{getattr(card, 'fn', '') or 'contact'}: label uses address #{n} of "
            f"{len(addresses)} ({why}: {(getattr(chosen, 'street', '') or '').splitlines()[0] if getattr(chosen, 'street', '') else '—'}), "
            f"not the one in the edit form")


def _addr_key(card):
    a = _preferred_address(card)
    if not a:
        return None
    street = re.sub(r"\s+", " ", (getattr(a, "street", None) or "").strip().lower())
    postcode = re.sub(r"\s+", "", (getattr(a, "postal_code", None) or "").strip().lower())
    return (street, postcode) if street or postcode else None


def _split_lines(value: str | None) -> list[str]:
    """Split a vCard address component on embedded newlines (Apple/iCloud put
    multi-line streets in one STREET component) and collapse inner whitespace."""
    out = []
    for part in re.split(r"\r\n|\r|\n|\\n", value or ""):
        part = re.sub(r"\s+", " ", part).strip(" ,")
        if part:
            out.append(part)
    return out


def _format_address(card, include_country: bool) -> list[str]:
    """Postal lines in Royal Mail order.

    Sub-building (vCard "extended", e.g. "Flat 12") goes *above* the street,
    multi-line streets are kept as separate lines, PO Box follows the street,
    then post town, county/region, postcode on its own line and — for non-UK
    addresses only — the country last.
    """
    a = _preferred_address(card)
    if not a:
        return []
    lines: list[str] = []

    def add(value):
        for line in _split_lines(value):
            if line.casefold() not in {x.casefold() for x in lines}:
                lines.append(line)

    street_lines = _split_lines(getattr(a, "street", None))
    street_blob = " ".join(street_lines).casefold()
    for ext in _split_lines(getattr(a, "extended", None)):
        # Skip "Flat 12" if the street text already contains it.
        if ext.casefold() not in street_blob:
            add(ext)
    for line in street_lines:
        add(line)
    po_box = (getattr(a, "po_box", None) or "").strip()
    if po_box:
        add(po_box if re.match(r"(?i)^(p\.?\s*o\.?\s*)?box\b", po_box) else f"PO Box {po_box}")
    add(getattr(a, "locality", None))
    add(getattr(a, "region", None))
    add(getattr(a, "postal_code", None))
    country = (getattr(a, "country", None) or "").strip()
    if include_country and country and country.lower() not in _UK_COUNTRIES:
        add(country)
    return lines


def _is_uk_address(card) -> bool:
    a = _preferred_address(card)
    country = (getattr(a, "country", None) or "").strip().lower() if a else ""
    return not country or country in _UK_COUNTRIES


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

        source = card
        warnings: list[str] = []
        if partner is not None:
            mine = _format_address(card, True)
            theirs = _format_address(partner, True)
            if mine != theirs:
                # Same street + postcode but other lines differ (country, town…):
                # trust the card edited most recently and say so.
                newer = partner if (getattr(partner, "rev", None) or "") > (getattr(card, "rev", None) or "") else card
                older = card if newer is partner else partner
                source = newer
                diff = [x for x in _format_address(older, True) if x not in _format_address(newer, True)]
                warnings.append(
                    f"couple address mismatch — using {getattr(newer, 'fn', '')}'s card (edited most recently); "
                    f"{getattr(older, 'fn', '')}'s card differs"
                    + (f" ({', '.join(diff)})" if diff else "")
                    + " — correct it so both cards agree"
                )
        note = _address_note(source)
        if note:
            warnings.append(note)
        a = _preferred_address(source)
        missing_postcode = not (getattr(a, "postal_code", None) or "").strip()
        uk = _is_uk_address(source)
        common = {
            "address": _format_address(source, include_country),
            "missing_postcode": missing_postcode,
            "uk": uk,
            "warnings": warnings,
        }
        if partner is not None:
            if uid:
                used.add(uid)
            if getattr(partner, "uid", None):
                used.add(partner.uid)
            records.append({"name": _format_couple(card, partner, style), "merged": True, **common})
        elif partner_text:
            if uid:
                used.add(uid)
            records.append({"name": _format_couple_from_text(card, partner_text, style), "merged": True, **common})
        else:
            if uid:
                used.add(uid)
            records.append({"name": _format_single(card), "merged": False, **common})

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
        "address_warnings": [{"name": r["name"], "warnings": r["warnings"]}
                             for r in records if r.get("warnings")],
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


def _pick_test_records(records: list[dict], n: int = 3) -> list[dict]:
    """Pick the labels most likely to fail, so a 3-label test proves the worst
    case rather than the first three alphabetically: most lines, longest single
    line (name or address) and longest name."""
    if len(records) <= n:
        return list(records)

    def lines(r):
        return [r["name"], *r["address"]]

    rankers = [
        lambda r: (len(r["address"]), max(map(len, lines(r)))),
        lambda r: max(map(len, lines(r))),
        lambda r: len(r["name"]),
    ]
    chosen: list[int] = []
    for rank in rankers:
        for i in sorted(range(len(records)), key=lambda i: rank(records[i]), reverse=True):
            if i not in chosen:
                chosen.append(i)
                break
    return [records[i] for i in chosen[:n]]


# Auto-fit script embedded in roll-label output. For each label it shrinks the
# text (down to MIN of the profile size) until every line fits on one line and
# the block fits the label height; if that fails it allows wrapping and tries
# again; if *that* fails the label is flagged red. Runs on load and again on
# beforeprint, so the printed geometry is the one that was checked.
_FIT_JS = r"""
(function () {
  var MIN = 0.72, STEP = 0.96;
  function over(lbl) {
    var inner = lbl.firstElementChild;
    // offsetHeight is layout size, unaffected by the print-time rotation
    if (inner.offsetHeight > lbl.clientHeight + 0.5) return true;
    var rows = lbl.querySelectorAll('.name, .aline');
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].scrollWidth > rows[i].clientWidth + 0.5) return true;
    }
    return false;
  }
  function shrink(lbl) {
    var k = 1;
    lbl.style.setProperty('--k', k);
    while (over(lbl) && k > MIN) {
      k = Math.max(MIN, k * STEP);
      lbl.style.setProperty('--k', k.toFixed(3));
    }
    return k;
  }
  function fit(lbl) {
    lbl.classList.remove('wrap', 'overflow', 'shrunk');
    var k = shrink(lbl);
    if (over(lbl)) { lbl.classList.add('wrap'); k = shrink(lbl); }
    if (over(lbl)) lbl.classList.add('overflow');
    else if (k < 0.999 || lbl.classList.contains('wrap')) lbl.classList.add('shrunk');
  }
  function names(list) {
    return Array.prototype.map.call(list, function (l) {
      return l.getAttribute('data-name');
    }).join(' · ');
  }
  function run() {
    var labels = document.querySelectorAll('.label');
    Array.prototype.forEach.call(labels, fit);
    var bad = document.querySelectorAll('.label.overflow');
    var adj = document.querySelectorAll('.label.shrunk');
    var el = document.getElementById('fit-report');
    if (!el) return;
    if (bad.length) {
      el.className = 'fit-bad';
      el.textContent = '✖ ' + bad.length + ' label(s) still do not fit and WILL be clipped — shorten the name/address in vCard Studio and regenerate: ' + names(bad);
    } else {
      el.className = 'fit-ok';
      el.textContent = '✔ All ' + labels.length + ' label(s) fit the printable area.' +
        (adj.length ? ' ' + adj.length + ' were auto-shrunk or wrapped (amber): ' + names(adj) : '');
    }
  }
  var ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
  ready.then(run);
  window.addEventListener('beforeprint', run);
})();
"""


def _render_roll_labels(records, profile, header_html, test_banner, title) -> str:
    """One label per page, page size = physical label, identical geometry on
    screen and in print (so the on-screen check is the printed result).

    print_rotate profiles: the label is read landscape (w × h) but the driver's
    paper is portrait (h wide × w long, h = tape width). The printed page is
    emitted in the driver's own portrait size with the label face rotated 90°
    inside it, so neither the browser nor the driver has to rotate or scale
    anything. The screen view stays upright for checking; fitting uses layout
    sizes, which a CSS rotation does not change.
    """
    t, r, b, l = profile["pad_mm"]
    w, h = profile["page_w_mm"], profile["page_h_mm"]
    rotate = bool(profile.get("print_rotate"))
    page_size = f"{h}mm {w}mm" if rotate else f"{w}mm {h}mm"
    print_rot_css = (
        f"@media print {{\n"
        f"  .sheet {{ width: {h}mm; height: {w - 0.2:.2f}mm; }}\n"
        f"  .face {{ position: absolute; top: 0; left: 0; transform-origin: 0 0;\n"
        f"          transform: translateX({h - 0.2:.2f}mm) rotate(90deg); }}\n"
        f"}}\n"
        if rotate else ""
    )
    lh = profile.get("line_height", 1.3)
    labels = []
    for rec in records:
        rows = "".join(f"<div class='aline'>{esc_html(line)}</div>" for line in rec["address"])
        mark = " <span class='mmark' title='couple merged'>⚭</span>" if rec["merged"] else ""
        labels.append(
            f"<div class='sheet'><div class='face'><div class='label' data-name='{esc_html(rec['name'])}'>"
            f"<div class='inner'><div class='name'>{esc_html(rec['name'])}{mark}</div>"
            f"<div class='addr'>{rows}</div></div></div></div></div>"
        )

    css = f"""
@page {{ size: {page_size}; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #fff; }}
body {{ font-family: Arial, Helvetica, "Liberation Sans", sans-serif; color: #000;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
/* 0.2 mm under the page height guards against a rounding overflow that would
   otherwise push a blank page (= a wasted, separately cut label). */
.sheet {{ width: {w}mm; height: {h - 0.2:.2f}mm; overflow: hidden; position: relative;
         break-after: page; page-break-after: always; }}
.face {{ width: {w}mm; height: {h - 0.2:.2f}mm; padding: {t}mm {r}mm {b}mm {l}mm; }}
.sheet:last-of-type {{ break-after: auto; page-break-after: auto; }}
.label {{ --k: 1; width: 100%; height: 100%; overflow: hidden;
         display: flex; flex-direction: column; justify-content: center;
         font-size: calc({profile['font_pt']}pt * var(--k)); line-height: {lh}; }}
.inner {{ width: 100%; }}
.name {{ font-size: calc({profile['name_pt']}pt * var(--k)); font-weight: 700;
        margin-bottom: calc(1mm * var(--k)); }}
.name, .aline {{ white-space: nowrap; overflow: hidden; }}
.label.wrap .name, .label.wrap .aline {{ white-space: normal; overflow-wrap: anywhere; }}
/* thermal head: solid black only — greys are dithered and print fuzzy */
.name, .addr, .aline {{ color: #000; }}
/* ⚭ marker sits outside the text flow so screen layout == print layout */
.mmark {{ position: absolute; top: 0.3mm; right: 0.6mm; font: 400 7pt sans-serif; color: #08a; }}
.test-banner, .screen-header {{ display: none; }}
@media screen {{
  html, body {{ background: #d9d9d9; }}
  body {{ padding: 14px; }}
  .test-banner {{ display: block; background: #ffd400; color: #000; text-align: center;
                 font: bold 11pt sans-serif; padding: 6px; margin: -14px -14px 12px; }}
  .screen-header {{ display: block; font: 11px/1.6 monospace; color: #333; background: #fff;
                   border: 1px solid #bbb; padding: 10px 14px; margin: 0 auto 14px; max-width: 760px; }}
  .screen-header ol, .screen-header ul {{ margin: 6px 0 0 20px; }}
  .warn {{ color: #a60; }}
  #fit-report {{ display: block; margin-top: 8px; padding: 6px 8px; font-weight: bold; }}
  .fit-ok {{ background: #e5f6e5; color: #060; }}
  .fit-bad {{ background: #fde2e2; color: #b00; }}
  .sheet {{ background: #fff; margin: 10px auto; box-shadow: 0 1px 4px rgba(0,0,0,.25); }}
  .label {{ outline: 1px dashed #bbb; }}
  .label.shrunk {{ outline: 2px solid #e8a000; }}
  .label.overflow {{ outline: 3px solid #d00; }}
}}
@media print {{ .mmark {{ display: none; }} }}
{print_rot_css}"""
    return (
        f"<!doctype html>\n<html lang='en'><head><meta charset='utf-8'><title>{esc_html(title)}</title>"
        f"<style>{css}</style></head><body>{test_banner}{header_html}"
        f"{''.join(labels)}<script>{_FIT_JS}</script></body></html>"
    )


def _render_flow_labels(records, profile, header_html, test_banner, title) -> str:
    """Legacy/sheet layout for profiles without numeric geometry (e.g. the
    generic A4 module): labels flow down the page, never split across pages."""
    labels = []
    for rec in records:
        rows = "".join(f"<div class='aline'>{esc_html(line)}</div>" for line in rec["address"])
        mark = " <span class='mmark'>⚭</span>" if rec["merged"] else ""
        labels.append(f"<div class='label'><div class='name'>{esc_html(rec['name'])}{mark}</div>"
                      f"<div class='addr'>{rows}</div></div>")
    css = f"""
@page {{ {profile['page_css']} }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; background: white; color: #000; }}
.label {{ {profile['label_css']} break-inside: avoid; page-break-inside: avoid; }}
.name {{ font-size: {profile['name_size']}; font-weight: bold; margin-bottom: 1.5mm; }}
.mmark {{ font-size: 7pt; color: #555; font-weight: normal; }}
.test-banner {{ background: #ff0; text-align: center; font: 10pt sans-serif; padding: 4px; }}
.screen-header {{ font: 11px monospace; color: #555; margin: 10px auto 16px; padding: 8px;
                 max-width: 750px; border: 1px solid #ddd; }}
.screen-header ol, .screen-header ul {{ margin: 6px 0 0 20px; }} .warn {{ color: #a60; }} #fit-report {{ display: none; }}
@media screen {{ body {{ background: #eee; padding: 10px; }} .label {{ background: #fff; }} .screen-header {{ background: #fff; }} }}
@media print {{ .screen-header, .test-banner, .mmark {{ display: none; }} }}
"""
    return (
        f"<!doctype html>\n<html lang='en'><head><meta charset='utf-8'><title>{esc_html(title)}</title>"
        f"<style>{css}</style></head><body>{test_banner}{header_html}{''.join(labels)}</body></html>"
    )


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
    steps = next((m["print_steps"] for m in get_all_modules() if m["printer_id"] == printer_id), [])

    indices = body.get("indices")
    if indices is not None:
        indices = [int(i) for i in indices]
    all_records = build_label_records(cards, category, style, include_country, indices)
    records = _pick_test_records(all_records) if test_mode else all_records

    total = len(records)
    merged = sum(1 for r in records if r["merged"])
    no_postcode = [r["name"] for r in records if r.get("missing_postcode") and r.get("uk", True)]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    cat_label = category or "all contacts"
    roll = profile.get("layout") == "roll" and "page_w_mm" in profile

    test_banner = (
        "<div class='test-banner'>⚠ TEST — the 3 hardest labels "
        f"(of {len(all_records)}): most lines, longest line, longest name</div>"
        if test_mode else ""
    )
    size_line = (
        f"Physical page: <strong>{profile['page_w_mm']} × {profile['page_h_mm']} mm</strong> · "
        f"driver paper: <strong>{esc_html(profile.get('driver_paper', ''))}</strong><br>"
        if roll else ""
    )
    warn_line = (
        f"<span class='warn'>⚠ {len(no_postcode)} UK label(s) have no postcode: "
        f"{esc_html(' · '.join(no_postcode))}</span><br>"
        if no_postcode else ""
    )
    addr_warn = [(r["name"], w) for r in all_records for w in r.get("warnings", [])]
    if addr_warn:
        warn_line += (
            f"<span class='warn'>⚠ {len(addr_warn)} address warning(s) across all "
            f"{len(all_records)} labels — check before printing:</span><ul class='warn'>"
            + "".join(f"<li><strong>{esc_html(n)}</strong>: {esc_html(w)}</li>" for n, w in addr_warn)
            + "</ul>"
        )
    steps_html = "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>" if steps else ""
    header_html = (
        "<div class='screen-header'><strong>vCard Studio — Address Labels</strong><br>"
        f"Category: <strong>{esc_html(cat_label)}</strong> · {total} label{'s' if total != 1 else ''}"
        f" · {merged} couple{'s' if merged != 1 else ''} merged ⚭ (symbol not printed)<br>"
        f"Profile: <strong>{esc_html(printer_id)} / {esc_html(profile_id)}</strong> · "
        f"{esc_html(profile.get('name', ''))} · generated {generated}<br>"
        f"{size_line}{warn_line}{steps_html}"
        "<span id='fit-report'></span></div>"
    )
    title = f"Address Labels — {cat_label}"
    render = _render_roll_labels if roll else _render_flow_labels
    html = render(records, profile, header_html, test_banner, title)

    print_dir.mkdir(parents=True, exist_ok=True)
    safe_cat = re.sub(r"[^\w-]", "-", category or "all").strip("-") or "all"
    suffix = "-TEST" if test_mode else ""
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = print_dir / f"labels-{safe_cat}-{profile_id}-{stamp}{suffix}.html"
    out.write_text(html, encoding="utf-8")
    return {
        "ok": True, "file": str(out), "filename": out.name,
        "total": total, "merged": merged, "test_mode": test_mode,
        "missing_postcode": no_postcode,
        "address_warnings": len(addr_warn),
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
