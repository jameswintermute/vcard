from pathlib import Path

from vcard_normalizer.model import Address, Card, NameComponents, Related
from vcard_normalizer.printing import (
    build_label_records,
    generate_address_book,
    generate_labels,
    label_options,
    preview_labels,
    print_modules,
)


def _card(fn, given, family, uid, *, prefix="", gender=None, address=None):
    return Card(
        raw=None,
        fn=fn,
        name=NameComponents(given=given, family=family, prefix=prefix),
        uid=uid,
        gender=gender,
        addresses=[address] if address else [],
    )


def test_print_modules_discover_bundled_printers():
    result = print_modules()
    assert result["ok"] is True
    ids = {m["printer_id"] for m in result["modules"]}
    assert "brother_ql820nwb" in ids
    assert "generic_a4" in ids


def test_label_records_merge_linked_couple_at_same_address():
    a1 = Address(street="1 High Street", locality="Weybridge", postal_code="KT13 8AA", country="United Kingdom")
    a2 = Address(street="1 High Street", locality="Weybridge", postal_code="KT13 8AA", country="United Kingdom")
    james = _card("James Smith", "James", "Smith", "j", prefix="Mr", gender="M", address=a1)
    ruth = _card("Ruth Smith", "Ruth", "Smith", "r", prefix="Mrs", gender="F", address=a2)
    james.related = [Related(rel_type="spouse", uid="r", text="Ruth Smith")]
    ruth.related = [Related(rel_type="spouse", uid="j", text="James Smith")]

    records = build_label_records([james, ruth], style="british_formal", include_country=True)

    assert len(records) == 1
    assert records[0]["merged"] is True
    assert records[0]["name"] == "Mr & Mrs J Smith"
    assert records[0]["address"] == ["1 High Street", "Weybridge", "KT13 8AA"]


def test_labels_use_preferred_address_not_first_address():
    old = Address(street="Old Address", postal_code="OLD 1", type="HOME")
    preferred = Address(street="Preferred Address", postal_code="NEW 1", pref=True)
    card = _card("Alice Example", "Alice", "Example", "a", address=old)
    card.addresses.append(preferred)

    records = build_label_records([card])

    assert records[0]["address"][0] == "Preferred Address"


def test_preview_reports_contacts_without_postal_address():
    with_addr = _card("Alice Example", "Alice", "Example", "a", address=Address(street="1 High Street"))
    missing = _card("Bob Missing", "Bob", "Missing", "b")

    result = preview_labels([with_addr, missing], {})

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["no_address"] == [{"fn": "Bob Missing", "_idx": 1}]


def test_label_options_offer_linked_partner():
    address = Address(street="1 High Street", postal_code="KT13 8AA")
    james = _card("James Smith", "James", "Smith", "j", prefix="Mr", gender="M", address=address)
    ruth = _card("Ruth Smith", "Ruth", "Smith", "r", prefix="Mrs", gender="F", address=Address(street="1 High Street", postal_code="KT13 8AA"))
    james.related = [Related(rel_type="spouse", uid="r", text="Ruth Smith")]

    result = label_options([james, ruth], {"indices": [0], "style": "british_formal"})

    assert result["ok"] is True
    assert result["options"][0]["couple_idx"] == 1
    assert result["options"][0]["couple_name"] == "Mr & Mrs J Smith"


def test_generate_labels_and_address_book(tmp_path: Path):
    card = _card(
        "Alice Example", "Alice", "Example", "a",
        address=Address(street="1 High Street", locality="Weybridge", postal_code="KT13 8AA"),
    )

    labels = generate_labels(
        [card], tmp_path,
        {"printer_id": "brother_ql820nwb", "profile_id": "DK22205", "style": "individual"},
    )
    assert labels["ok"] is True
    label_file = tmp_path / labels["filename"]
    assert label_file.exists()
    assert "Alice Example" in label_file.read_text(encoding="utf-8")

    book = generate_address_book([card], tmp_path, {"paper": ["A4"]})
    assert book["ok"] is True
    book_file = tmp_path / book["filename"]
    assert book_file.exists()
    assert "Alice Example" in book_file.read_text(encoding="utf-8")


# ── Brother QL geometry and label-engine regressions ─────────────────────────
# Hardware print areas from Brother's QL-800/810W/820NWB Raster Command
# Reference §2.3: unprintable strip on long edges, plus end offset on die-cut.

from vcard_normalizer.print_modules import brother_ql820nwb as ql
from vcard_normalizer.printing import _format_address, _pick_test_records

_HW = {  # id: (tape width across head mm, long-edge strip mm, end offset mm)
    "DK22205": (62.0, 1.5, 0.0),
    "DK22223": (50.0, 1.5, 0.0),
    "DK11208": (38.0, 1.5, 3.0),
    "DK11201": (29.0, 1.5, 3.0),
    "DK11209": (62.0, 1.5, 3.0),
}


def test_every_brother_profile_fits_the_hardware_print_area():
    profiles = {p["id"]: p for p in ql.LABEL_PROFILES}
    assert set(_HW) <= set(profiles)
    for pid, (across, edge, end) in _HW.items():
        p = profiles[pid]
        t, r, b, l = p["pad_mm"]
        w, h = p["page_w_mm"], p["page_h_mm"]
        if w != across:                             # landscape: label ends are left/right
            assert h == across and p["media"] == "die-cut", pid
            assert min(t, b) >= edge and min(l, r) >= end, pid
        else:                                       # text runs across the tape
            assert w == across, pid
            assert min(l, r) >= edge and min(t, b) >= end, pid


def test_address_lines_follow_royal_mail_order_and_split_multiline_streets():
    card = _card("A B", "A", "B", "x", address=Address(
        extended="Flat 12", street="The Old Rectory\nChurch Lane", po_box="",
        locality="Ely", region="Cambs", postal_code="CB7 4AA", country="United Kingdom"))
    assert _format_address(card, True) == [
        "Flat 12", "The Old Rectory", "Church Lane", "Ely", "Cambs", "CB7 4AA"]


def test_extended_not_duplicated_when_already_in_street():
    card = _card("A B", "A", "B", "x", address=Address(extended="Flat 2", street="Flat 2, 10 High St"))
    assert _format_address(card, False) == ["Flat 2, 10 High St"]


def test_roll_labels_never_truncate_and_hide_merge_mark_in_print(tmp_path: Path):
    a = Address(street="1 High Street", locality="Weybridge", postal_code="KT13 8AA")
    j = _card("James Smith", "James", "Smith", "j", prefix="Mr", gender="M", address=a)
    r = _card("Ruth Smith", "Ruth", "Smith", "r", prefix="Mrs", gender="F",
              address=Address(street="1 High Street", locality="Weybridge", postal_code="KT13 8AA"))
    j.related = [Related(rel_type="spouse", uid="r")]
    out = generate_labels([j, r], tmp_path, {"printer_id": "brother_ql820nwb", "profile_id": "DK11201"})
    html = (tmp_path / out["filename"]).read_text(encoding="utf-8")
    assert "text-overflow" not in html and "ellipsis" not in html
    assert "size: 90mm 29mm; margin: 0;" in html
    assert "@media print { .mmark { display: none; } }" in html
    assert ".sheet:last-of-type" in html


def test_missing_uk_postcode_is_reported(tmp_path: Path):
    card = _card("No Code", "No", "Code", "n", address=Address(street="5 Mill Road", locality="Ely"))
    out = generate_labels([card], tmp_path, {"printer_id": "brother_ql820nwb", "profile_id": "DK22205"})
    assert out["missing_postcode"] == ["No Code"]


def test_test_mode_picks_hardest_labels():
    recs = [
        {"name": "Mr A Bee", "address": ["1 St", "Town", "AB1 2CD"], "merged": False},
        {"name": "Mr C Dee", "address": ["1", "2", "3", "4", "5", "6"], "merged": False},
        {"name": "Lt Col & Mrs A Featherstonehaugh-Whittingham", "address": ["1 St"], "merged": True},
        {"name": "Ms E Eff", "address": ["An extremely long street name for testing purposes", "X"], "merged": False},
        {"name": "Mr G Gee", "address": ["1 St"], "merged": False},
    ]
    picked = [r["name"] for r in _pick_test_records(recs)]
    assert picked == ["Mr C Dee", "Ms E Eff", "Lt Col & Mrs A Featherstonehaugh-Whittingham"]


# ── Stale-country regressions: edited address must win ──────────────────────

def _us(country, **kw):
    return Address(street="46 Example Blvd", locality="Springfield", region="Illinois",
                   postal_code="IL 62701", country=country, **kw)


def test_edited_first_address_beats_stale_pref_duplicate_of_same_place():
    card = _card("Tom Smith", "Tom", "Smith", "t", prefix="Mr", gender="M", address=_us("United States"))
    card.addresses.append(_us("Australia", type="HOME", pref=True))   # hidden stale copy
    rec = build_label_records([card], style="individual")[0]
    assert rec["address"][-1] == "United States"
    assert "Australia" not in rec["address"]


def test_genuinely_different_preferred_address_still_wins_and_is_flagged():
    card = _card("Tom Smith", "Tom", "Smith", "t", address=Address(street="1 Work Rd", postal_code="W1 1AA"))
    card.addresses.append(Address(street="9 Home Lane", postal_code="H1 1AA", pref=True))
    rec = build_label_records([card], style="individual")[0]
    assert rec["address"][0] == "9 Home Lane"
    assert any("address #2" in w for w in rec["warnings"])


def test_couple_uses_most_recently_edited_card_and_warns_on_mismatch():
    tom = _card("Tom Smith", "Tom", "Smith", "t", prefix="Mr", gender="M", address=_us("Australia"))
    ann = _card("Ann Smith", "Ann", "Smith", "a", prefix="Mrs", gender="F", address=_us("United States"))
    tom.rev, ann.rev = "20250101T000000Z", "20261124T142716Z"      # Ann's card was just corrected
    tom.related = [Related(rel_type="spouse", uid="a")]
    ann.related = [Related(rel_type="spouse", uid="t")]
    for order in ([tom, ann], [ann, tom]):
        rec = build_label_records(order, style="british_formal")[0]
        assert rec["merged"] is True
        assert rec["address"][-1] == "United States"
        assert any("mismatch" in w and "Australia" in w for w in rec["warnings"])
    assert preview_labels([tom, ann], {})["address_warnings"]
