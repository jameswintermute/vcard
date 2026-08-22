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
