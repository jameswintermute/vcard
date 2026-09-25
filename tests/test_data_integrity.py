"""Regression tests for master-data integrity and Apple/iCloud round trips."""
from __future__ import annotations

from pathlib import Path

from vcard_normalizer.dedupe import merge_cluster_auto
from vcard_normalizer.exporter import export_vcards
from vcard_normalizer.io import _sanitise_vcf, read_vcards_from_files
from vcard_normalizer.master import merge_import_into_master
from vcard_normalizer.merge import merge_cards_preserving_base
from vcard_normalizer.model import Address, Card, NameComponents, Related, TypedValue
from vcard_normalizer.normalize import normalize_cards


def _card(**kwargs) -> Card:
    return Card(raw=None, **kwargs)


def test_import_enriches_but_never_replaces_master_scalars():
    master = _card(
        uid="vcard-studio-master",
        fn="Jane Master",
        name=NameComponents(given="Jane", family="Master", prefix="Dr"),
        emails=["jane@example.com"],
        typed_emails=[TypedValue("jane@example.com", type="HOME")],
        tels=["+44 7700 900001"],
        typed_tels=[TypedValue("+44 7700 900001", type="CELL", label="iPhone")],
        title="Canonical title",
        note="Carefully curated central note",
        anniversary="2010-06-12",
        gender="F",
        categories=["Family"],
        related=[Related(rel_type="spouse", uid="vcard-studio-spouse")],
        addresses=[Address(street="1 Master Road", locality="London", type="HOME")],
    )
    incoming = _card(
        uid="apple-vendor-123",
        external_uids=["apple-vendor-123"],
        fn="Jane Different",
        name=NameComponents(given="Jane", family="Different"),
        emails=["jane@example.com", "jane@work.example"],
        typed_emails=[TypedValue("jane@work.example", type="WORK")],
        tels=["+44 7700 900001", "+44 7700 900002"],
        typed_tels=[TypedValue("+44 7700 900002", type="WORK")],
        title="Stale Apple title",
        note="Stale Apple note",
        categories=["Friends"],
        addresses=[Address(street="2 New Road", locality="London", type="WORK")],
        _source_files=["icloud"],
    )

    merged, added, updated = merge_import_into_master([incoming], [master])
    assert added == 0
    assert updated == 1
    assert len(merged) == 1

    card = merged[0]
    assert card.uid == "vcard-studio-master"
    assert card.fn == "Jane Master"
    assert card.name.family == "Master"
    assert card.title == "Canonical title"
    assert card.note == "Carefully curated central note"
    assert card.anniversary == "2010-06-12"
    assert card.gender == "F"
    assert set(card.emails) == {"jane@example.com", "jane@work.example"}
    assert set(card.tels) == {"+44 7700 900001", "+44 7700 900002"}
    assert set(card.categories) == {"Family", "Friends"}
    assert len(card.addresses) == 2
    assert "apple-vendor-123" in card.external_uids
    assert "icloud" in card._source_files
    assert any("retained master" in change.lower() for change in card._changes)


def test_duplicate_merge_unions_rich_fields_without_replacing_first_card():
    base = _card(
        uid="stable-id",
        fn="Alex Primary",
        emails=["a@example.com"],
        addresses=[Address(street="1 Home St", type="HOME", label="Home")],
        related=[Related(rel_type="spouse", uid="spouse-id")],
        nicknames=["Al"],
        urls=[TypedValue("https://example.com", type="HOME")],
        member=["member-a"],
    )
    other = _card(
        uid="other-id",
        fn="Alex Secondary",
        emails=["b@example.com"],
        addresses=[Address(street="2 Work St", type="WORK", label="Office")],
        related=[Related(rel_type="parent", text="Pat")],
        nicknames=["Lex"],
        urls=[TypedValue("https://work.example", type="WORK")],
        member=["member-b"],
    )

    merged = merge_cluster_auto([base, other])
    assert merged.uid == "stable-id"
    assert merged.fn == "Alex Primary"
    assert set(merged.emails) == {"a@example.com", "b@example.com"}
    assert {a.street for a in merged.addresses} == {"1 Home St", "2 Work St"}
    assert len(merged.related) == 2
    assert set(merged.nicknames) == {"Al", "Lex"}
    assert {u.value for u in merged.urls} == {"https://example.com", "https://work.example"}
    assert set(merged.member) == {"member-a", "member-b"}
    assert "other-id" in merged.external_uids


def test_same_address_merges_apple_label_metadata():
    base = _card(addresses=[Address(street="1 High St", locality="London")])
    incoming = _card(
        addresses=[
            Address(
                street="1 High St",
                locality="London",
                type="HOME",
                label="Parents",
                pref=True,
                apple_country_code="gb",
            )
        ]
    )
    merged, changed = merge_cards_preserving_base(base, incoming)
    assert changed
    assert len(merged.addresses) == 1
    assert merged.addresses[0].type == "HOME"
    assert merged.addresses[0].label == "Parents"
    assert merged.addresses[0].pref is True
    assert merged.addresses[0].apple_country_code == "gb"


def test_apple_sanitiser_preserves_property_boundaries():
    raw = (
        "BEGIN:VCARD\r\n"
        "item1.TEL;TYPE=CELL:07700900001\r\n"
        "item1.X-ABLabel:iPhone\r\n"
        "EMAIL:a@example.com\r\n"
        "END:VCARD\r\n"
    )
    cleaned = _sanitise_vcf(raw, "icloud")
    assert "TEL;TYPE=CELL;X-VCS-APPLE-LABEL-B64=" in cleaned
    assert "\r\nEMAIL:a@example.com\r\n" in cleaned
    assert "X-ABLabel" not in cleaned


def test_icloud_grouped_labels_are_preserved(tmp_path: Path):
    source = tmp_path / "icloud.vcf"
    source.write_text(
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        "FN:Apple Contact\n"
        "item1.TEL;TYPE=CELL;TYPE=pref:07700900001\n"
        "item1.X-ABLabel:iPhone\n"
        "item2.EMAIL;TYPE=INTERNET:apple@example.com\n"
        "item2.X-ABLabel:_$!<Work>!$_\n"
        "item3.ADR;TYPE=HOME:;;1 High St;London;;W1A 1AA;United Kingdom\n"
        "item3.X-ABLabel:_$!<Home>!$_\n"
        "item3.X-ABADR:gb\n"
        "item4.URL:https://example.com\n"
        "item4.X-ABLabel:_$!<HomePage>!$_\n"
        "END:VCARD\n",
        encoding="utf-8",
    )

    cards = normalize_cards(read_vcards_from_files([source]))
    assert len(cards) == 1
    card = cards[0]
    assert card.typed_tels[0].label == "iPhone"
    assert card.typed_tels[0].pref is True
    assert card.typed_emails[0].label == "Work"
    assert card.addresses[0].type == "HOME"
    assert card.addresses[0].label == "Home"
    assert card.addresses[0].apple_country_code == "gb"
    assert card.urls[0].label == "HomePage"


def test_vendor_uid_becomes_alias_and_survives_master_roundtrip(tmp_path: Path):
    source = tmp_path / "icloud.vcf"
    source.write_text(
        "BEGIN:VCARD\nVERSION:3.0\nFN:Vendor UID\n"
        "UID:AB12345-provider-generated\nX-ABUID:ABUID-456\nEMAIL:uid@example.com\nEND:VCARD\n",
        encoding="utf-8",
    )
    card = normalize_cards(read_vcards_from_files([source]))[0]
    assert card.uid.startswith("vcard-studio-")
    assert "AB12345-provider-generated" in card.external_uids
    assert "ABUID-456" in card.external_uids

    canonical = tmp_path / "master.vcf"
    export_vcards([card], canonical, target_version="4.0")
    loaded = normalize_cards(read_vcards_from_files([canonical]))[0]
    assert loaded.uid == card.uid
    assert "AB12345-provider-generated" in loaded.external_uids
    assert "ABUID-456" in loaded.external_uids


def test_member_roundtrip_for_org_uses_lossless_extension(tmp_path: Path):
    card = _card(
        uid="vcard-studio-org",
        fn="Example Org",
        org="Example Org",
        kind="org",
        member=["vcard-studio-a", "vcard-studio-b"],
    )
    out = tmp_path / "org.vcf"
    export_vcards([card], out, target_version="4.0")
    text = out.read_text(encoding="utf-8")
    assert "X-VCARD-STUDIO-MEMBER" in text
    # RFC MEMBER is reserved for KIND=group; org membership stays extension-backed.
    assert "\nMEMBER" not in text.replace("\r\n", "\n")

    loaded = normalize_cards(read_vcards_from_files([out]))[0]
    assert loaded.kind == "org"
    assert set(loaded.member) == {"vcard-studio-a", "vcard-studio-b"}


def test_apple_roundtrip_preserves_central_fields_and_emits_native_hints(tmp_path: Path):
    card = _card(
        uid="vcard-studio-rich",
        fn="Rich Contact",
        name=NameComponents(given="Rich", family="Contact"),
        emails=["rich@example.com"],
        typed_emails=[TypedValue("rich@example.com", type="WORK", label="Work", pref=True)],
        tels=["+44 7700 900123"],
        typed_tels=[TypedValue("+44 7700 900123", type="CELL", label="iPhone", pref=True)],
        urls=[TypedValue("https://example.com", label="HomePage")],
        nicknames=["Richie"],
        org="Example Ltd",
        kind="org",
        gender="M",
        anniversary="2012-09-15",
        categories=["Friends", "Work"],
        related=[Related(rel_type="spouse", uid="vcard-studio-spouse")],
        member=["vcard-studio-member"],
        addresses=[Address(
            street="1 High St",
            locality="London",
            country="United Kingdom",
            type="HOME",
            label="Home",
            apple_country_code="gb",
        )],
        note="Central note",
    )

    apple = tmp_path / "apple.vcf"
    export_vcards([card], apple, apple_compat=True)
    text = apple.read_text(encoding="utf-8")
    assert "VERSION:3.0" in text
    assert "X-ABSHOWAS:COMPANY" in text.upper()
    assert "X-ABLABEL" in text.upper()
    assert "X-ABDATE" in text.upper()
    assert "[vCS:" in text

    loaded = normalize_cards(read_vcards_from_files([apple]))[0]
    assert loaded.uid == card.uid
    assert loaded.kind == "org"
    assert loaded.gender == "M"
    assert loaded.anniversary == "2012-09-15"
    assert set(loaded.categories) == {"Friends", "Work"}
    assert loaded.note == "Central note"
    assert loaded.nicknames == ["Richie"]
    assert loaded.urls[0].label == "HomePage"
    assert loaded.typed_tels[0].label == "iPhone"
    assert loaded.addresses[0].label == "Home"
    assert loaded.addresses[0].apple_country_code == "gb"
    assert any(r.uid == "vcard-studio-spouse" for r in loaded.related)
    assert loaded.member == ["vcard-studio-member"]
