"""Regression: folded continuation lines of a dropped Apple grouped X-* property
must not be unfolded onto the preceding property (seen on a real iCloud export:
item1.X-ADDRESSING-GRAMMAR base64 appended to FN).

All data below is synthetic: fictional name, example.com address, Ofcom
drama-range number, and base64 of the alphabet rather than real Apple data.
"""
from __future__ import annotations

from pathlib import Path

from vcard_normalizer.io import _sanitise_vcf, read_vcards_from_files
from vcard_normalizer.normalize import normalize_cards

VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "N:Example;Ada;;Mrs;\r\n"
    "FN:Mrs Ada Example\r\n"
    "item1.X-ADDRESSING-GRAMMAR:QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlq\r\n"
    " a2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODlBQkNERUZHSElKS0xNTk9QUVJTVFVWV1hZWmFi\r\n"
    " Y2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MDEyMzQ1Njc4OQ==\r\n"
    "item2.TEL;TYPE=CELL:+44 7700 900\r\n"
    " 123\r\n"
    "item2.X-ABLabel:mob\r\n"
    " ile\r\n"
    "EMAIL:ada@example.com\r\n"
    "END:VCARD\r\n"
)


def _card(tmp_path: Path):
    f = tmp_path / "icloud.vcf"
    f.write_text(VCF, encoding="utf-8")
    cards = normalize_cards(read_vcards_from_files([f]))
    assert len(cards) == 1
    return cards[0]


def test_dropped_property_continuations_are_dropped():
    out = _sanitise_vcf(VCF, "t")
    assert "a2xtbm9w" not in out
    assert "Y2RlZmdo" not in out
    assert "X-ADDRESSING-GRAMMAR" not in out


def test_fn_not_polluted(tmp_path: Path):
    assert _card(tmp_path).fn == "Mrs Ada Example"


def test_kept_property_continuations_survive(tmp_path: Path):
    c = _card(tmp_path)
    assert any("123" in t.replace(" ", "") for t in c.tels)
    assert "ada@example.com" in c.emails
