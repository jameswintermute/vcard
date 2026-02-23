"""Tests for vcard-normalizer — M1 through M4 + multi-source merge."""
from __future__ import annotations

from pathlib import Path

import vobject

from vcard_normalizer.dedupe import _tel_key, merge_cluster_auto, similarity
from vcard_normalizer.exporter import export_vcards
from vcard_normalizer.formatters import (
    _infer_region_from_addresses,
    auto_tag_categories,
    classify_entities,
    normalize_phones_in_cards,
)
from vcard_normalizer.io import collect_merge_sources, read_vcards_from_files
from vcard_normalizer.model import Address, Card
from vcard_normalizer.normalize import normalize_cards, strip_photos
from vcard_normalizer.proprietary import DefaultStripper
from vcard_normalizer.report import build_source_counts, write_diff_file


# ── helpers ────────────────────────────────────────────────────────────────────

def _card(**kwargs) -> Card:
    return Card(raw=None, **kwargs)


def _raw_pair(fn: str = "Test", extra_props: str = "", label: str = "test"):
    vcf = f"BEGIN:VCARD\nVERSION:3.0\nFN:{fn}\n{extra_props}\nEND:VCARD"
    vc = list(vobject.readComponents(vcf))[0]
    return (vc, label)


# ── M1: Export ─────────────────────────────────────────────────────────────────

def test_export_basic(tmp_path: Path):
    c = _card(fn="Alice", emails=["alice@example.com"], tels=["+44 7980 220 220"])
    out = tmp_path / "out.vcf"
    n = export_vcards([c], out)
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "FN:Alice" in text
    assert "VERSION:4.0" in text


def test_export_categories(tmp_path: Path):
    c = _card(fn="Bob", categories=["Work", "Finance"])
    out = tmp_path / "out.vcf"
    export_vcards([c], out)
    text = out.read_text(encoding="utf-8")
    assert "CATEGORIES" in text
    assert "Finance" in text


def test_export_sorted(tmp_path: Path):
    cards = [_card(fn="Zara"), _card(fn="Alice"), _card(fn="Mike")]
    out = tmp_path / "sorted.vcf"
    export_vcards(cards, out)
    text = out.read_text(encoding="utf-8")
    positions = [text.index(name) for name in ("Alice", "Mike", "Zara")]
    assert positions == sorted(positions)


# ── M1: Proprietary stripping ──────────────────────────────────────────────────

def test_strip_apple_fields():
    pair = _raw_pair(extra_props="X-ABUID:abc123\nX-ADDRESSBOOKSERVER-KIND:individual",
                     label="icloud")
    cards = normalize_cards([pair])
    DefaultStripper().strip(cards[0])
    names = [ch.name.upper() for ch in cards[0].raw.getChildren()]
    assert "X-ABUID" not in names


def test_strip_logs_change():
    pair = _raw_pair(extra_props="X-GOOGLE-ETAG:xyz", label="protonmail")
    cards = normalize_cards([pair])
    DefaultStripper().strip(cards[0])
    assert any("proprietary" in chg.lower() for chg in cards[0]._changes)


# ── M1: Photo stripping ────────────────────────────────────────────────────────

def test_strip_photos_from_raw():
    pair = _raw_pair(extra_props="PHOTO;ENCODING=b;TYPE=JPEG:aGVsbG8=")
    vc, _ = pair
    count = strip_photos(vc)
    assert count == 1
    names = [ch.name.upper() for ch in vc.getChildren()]
    assert "PHOTO" not in names


def test_normalize_cards_strips_photo():
    pair = _raw_pair(fn="Charlie", extra_props="PHOTO;ENCODING=b;TYPE=JPEG:aGVsbG8=")
    cards = normalize_cards([pair])
    assert any("photo" in chg.lower() for chg in cards[0]._changes)


# ── M2: Phone normalisation ────────────────────────────────────────────────────

def test_phone_normalise_uk_mobile():
    card = _card(fn="Dave", tels=["07980220220"])
    normalize_phones_in_cards([card], default_region="GB")
    assert card.tels == ["+44 7980 220 220"]


def test_phone_invalid_left_unchanged():
    card = _card(fn="Frank", tels=["not-a-number"])
    normalize_phones_in_cards([card], default_region="GB")
    assert "not-a-number" in card.tels


def test_phone_infer_region_from_address():
    card = _card(fn="Grace", tels=["0412345678"],
                 addresses=[Address(country="Australia")])
    normalize_phones_in_cards([card], default_region="GB", infer_from_adr=True)
    assert any(t.startswith("+61") for t in card.tels)


def test_phone_change_logged():
    card = _card(fn="Henry", tels=["07700900000"])
    normalize_phones_in_cards([card], default_region="GB")
    assert any("reformatted" in chg.lower() for chg in card._changes)


def test_tel_key_dedup():
    assert _tel_key("+447980220220") == _tel_key("07980220220")


# ── M2: Deduplication ─────────────────────────────────────────────────────────

def test_dedupe_same_email():
    a = _card(fn="Alice", emails=["alice@example.com"])
    b = _card(fn="Alice Smith", emails=["alice@example.com"])
    assert similarity(a, b) >= 70


def test_dedupe_phone_local_vs_intl():
    a = _card(fn="Bob", tels=["07980220220"])
    b = _card(fn="Bob", tels=["+447980220220"])
    assert similarity(a, b) >= 40


def test_merge_auto_unions():
    a = _card(fn="Dan", emails=["dan@a.com"], tels=["07700900001"])
    b = _card(fn="Dan", emails=["dan@b.com"], tels=["07700900002"])
    merged = merge_cluster_auto([a, b])
    assert "dan@a.com" in merged.emails
    assert "dan@b.com" in merged.emails


def test_merge_auto_logs_change():
    a = _card(fn="Ed", emails=["ed@x.com"])
    b = _card(fn="Ed", emails=["ed@y.com"])
    merged = merge_cluster_auto([a, b])
    assert any("merged" in chg.lower() for chg in merged._changes)


# ── M3: Categories ────────────────────────────────────────────────────────────

def test_auto_tag_work_ltd():
    card = _card(fn="Acme Ltd", org="Acme Ltd")
    auto_tag_categories([card])
    assert "Work" in card.categories


def test_auto_tag_school():
    card = _card(fn="Springfield University", org="Springfield University")
    auto_tag_categories([card])
    assert "School" in card.categories


def test_auto_tag_no_false_positive():
    card = _card(fn="John Smith", emails=["john@gmail.com"])
    auto_tag_categories([card])
    assert "Work" not in card.categories


def test_classify_individual():
    card = _card(fn="Jane Doe")
    classify_entities([card])
    assert card.kind == "individual"


def test_classify_org():
    card = _card(fn="Widgets Inc", org="Widgets Inc")
    classify_entities([card])
    assert card.kind == "org"


def test_infer_region_iso2():
    card = _card(fn="X", addresses=[Address(country="AU")])
    assert _infer_region_from_addresses(card) == "AU"


# ── Multi-source merge ────────────────────────────────────────────────────────

def test_read_vcards_tracks_source(tmp_path: Path):
    vcf1 = tmp_path / "icloud.vcf"
    vcf2 = tmp_path / "protonmail.vcf"
    vcf1.write_text("BEGIN:VCARD\nVERSION:3.0\nFN:Alice\nEND:VCARD\n")
    vcf2.write_text("BEGIN:VCARD\nVERSION:3.0\nFN:Bob\nEND:VCARD\n")
    pairs = read_vcards_from_files([vcf1, vcf2])
    assert len(pairs) == 2
    labels = [label for _, label in pairs]
    assert "icloud" in labels
    assert "protonmail" in labels


def test_source_counts():
    pairs = [("a", "icloud"), ("b", "icloud"), ("c", "protonmail")]
    counts = build_source_counts(pairs)
    assert counts == {"icloud": 2, "protonmail": 1}


def test_normalize_cards_stamps_source():
    pair = _raw_pair(fn="Alice", label="icloud")
    cards = normalize_cards([pair])
    assert "icloud" in cards[0]._source_files


def test_collect_merge_sources(tmp_path: Path):
    (tmp_path / "icloud.vcf").write_text("")
    (tmp_path / "protonmail.vcf").write_text("")
    (tmp_path / "notes.txt").write_text("")   # should be ignored
    sources = collect_merge_sources(tmp_path)
    assert len(sources) == 2
    assert all(p.suffix == ".vcf" for p in sources)


def test_collect_merge_sources_missing_dir(tmp_path: Path):
    sources = collect_merge_sources(tmp_path / "nonexistent")
    assert sources == []


# ── M4: Report ────────────────────────────────────────────────────────────────

def test_write_diff_file(tmp_path: Path):
    card = _card(fn="Alice", _source_files=["icloud"])
    card.log_change("Phone reformatted: '07980220220' → '+44 7980 220 220'")
    out = tmp_path / "changes.txt"
    write_diff_file([card], out)
    text = out.read_text(encoding="utf-8")
    assert "Alice" in text
    assert "Phone reformatted" in text
    assert "icloud" in text


def test_model_log_change():
    card = _card(fn="Test")
    card.log_change("something happened")
    assert "something happened" in card._changes
