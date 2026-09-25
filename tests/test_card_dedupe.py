"""Per-card internal dedupe after round trips through other address books.

Synthetic data only: fictional name, example.com, 555-01xx fictional numbers.
"""
from __future__ import annotations

from pathlib import Path

from vcard_normalizer.exporter import card_to_vcf_text
from vcard_normalizer.io import read_vcards_from_files
from vcard_normalizer.merge import dedupe_card_fields
from vcard_normalizer.model import Card, TypedValue
from vcard_normalizer.normalize import normalize_cards

UID = "77777777-7777-4777-8777-777777777777"

# iOS-style values: bidi marks around numbers, NBSP spacing, mixed formatting,
# repeated email in another case, the same address twice (once with a type).
VCF = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\n"
    f"UID:{UID}\r\n"
    "FN:Mr Tom Example\r\nN:Example;Tom;;Mr;\r\n"
    "TEL;TYPE=CELL:+1 202 555 0143\r\n"
    "TEL:\u202a+1\u00a0202\u00a0555\u00a00143\u202c\r\n"
    "TEL:+12025550187\r\n"
    "TEL;TYPE=WORK:+1 (202) 555-0187\r\n"
    "EMAIL:tom@example.com\r\n"
    "EMAIL;TYPE=WORK:TOM@EXAMPLE.COM\r\n"
    "ADR:;;1 Test Street;Testville;;;United States\r\n"
    "ADR;TYPE=HOME:;;1 Test Street;Testville;;;United States\r\n"
    "CATEGORIES:Work,work\r\n"
    "END:VCARD\r\n"
)


def _load(tmp_path: Path, text: str = VCF) -> Card:
    f = tmp_path / "rt.vcf"
    f.write_text(text, encoding="utf-8")
    cards = normalize_cards(read_vcards_from_files([f]))
    assert len(cards) == 1
    return cards[0]


def test_duplicates_collapse_on_load(tmp_path):
    c = _load(tmp_path)
    assert len(c.tels) == 2 and len(c.typed_tels) == 2
    assert len(c.emails) == 1 and len(c.typed_emails) == 1
    assert len(c.addresses) == 1
    assert c.categories == ["Work"]


def test_types_from_duplicates_are_kept(tmp_path):
    c = _load(tmp_path)
    types = {tv.type.upper() for tv in c.typed_tels}
    assert types == {"CELL", "WORK"}
    assert c.typed_emails[0].type.upper() == "WORK"
    assert c.addresses[0].type.upper() == "HOME"


def test_invisible_characters_removed(tmp_path):
    c = _load(tmp_path)
    for v in c.tels:
        assert "\u202a" not in v and "\u202c" not in v and "\u00a0" not in v


def test_round_trip_is_stable(tmp_path):
    first = _load(tmp_path)
    again = _load(tmp_path, card_to_vcf_text(first, target_version="4.0"))
    assert len(again.tels) == 2 and len(again.emails) == 1 and len(again.addresses) == 1


def test_dedupe_is_idempotent_and_drops_self_links():
    from vcard_normalizer.model import Related
    c = Card(raw=None, fn="Tom", uid=UID,
             tels=["+12025550143", "+1 202 555 0143"],
             typed_tels=[TypedValue(value="+12025550143"), TypedValue(value="+1 202 555 0143", type="CELL")],
             related=[Related(rel_type="friend", uid=UID)])
    assert dedupe_card_fields(c) == 2
    assert c.typed_tels[0].type == "CELL"
    assert c.related == []
    assert dedupe_card_fields(c) == 0
