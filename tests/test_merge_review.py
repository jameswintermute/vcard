"""Reviewed zero-loss merge (MergePlan + /api/merge_* endpoints).

All contact data is synthetic: fictional names, example.com addresses and
Ofcom drama-range phone numbers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from vcard_normalizer import server
from vcard_normalizer.merge import MergePlan, repoint_links
from vcard_normalizer.normalize import normalize_cards
from vcard_normalizer.io import read_vcards_from_files

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
P = "33333333-3333-4333-8333-333333333333"

VCF = f"""BEGIN:VCARD
VERSION:4.0
UID:{A}
FN:Master Ada Example
N:Example;Ada;;Master;
EMAIL;TYPE=HOME:ada@example.com
TEL;TYPE=CELL:+44 7700 900123
BDAY:20160527
CATEGORIES:Family
NOTE:Swims on Tuesdays
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:{B}
FN:Master Ada Example
N:Example;Ada;;Master;
EMAIL:ADA@EXAMPLE.COM
TEL;TYPE=HOME:07700900123
BDAY:2016-05-28
ADR;TYPE=HOME:;;1 Test Street;Testtown;;TE1 1ST;United Kingdom
NOTE:Allergic to nuts\\n\\n---vCard Studio---\\nRELATED[parent]: urn:uuid:{P}\\nGENDER: M
END:VCARD
BEGIN:VCARD
VERSION:4.0
UID:{P}
FN:Mrs Eve Example
N:Example;Eve;;Mrs;
RELATED;TYPE=child:urn:uuid:{B}
END:VCARD
"""


@pytest.fixture
def cards(tmp_path: Path):
    f = tmp_path / "synthetic.vcf"
    f.write_text(VCF, encoding="utf-8")
    return normalize_cards(read_vcards_from_files([f]))


def by_uid(cards, uid):
    return next(c for c in cards if c.uid == uid)


def test_legacy_note_block_is_parsed_and_stripped(cards):
    b = by_uid(cards, B)
    assert b.note == "Allergic to nuts"
    assert any(r.uid == P and r.rel_type == "parent" for r in b.related)
    assert b.gender == "M"


def test_plan_dedupes_semantically(cards):
    plan = MergePlan([by_uid(cards, A), by_uid(cards, B)], region="GB").to_json()
    assert len(plan["lists"]["emails"]) == 1            # case-folded
    assert len(plan["lists"]["tels"]) == 1              # E.164, not raw string
    assert set(plan["lists"]["tels"][0]["types"]) == {"CELL", "HOME"}
    bday = next(s for s in plan["scalars"] if s["field"] == "bday")
    assert bday["conflict"] and len(bday["candidates"]) == 2
    assert "Swims on Tuesdays" in plan["default_note"]
    assert "Allergic to nuts" in plan["default_note"]


def test_plan_drops_self_links(cards):
    a, b = by_uid(cards, A), by_uid(cards, B)
    from vcard_normalizer.model import Related
    a.related.append(Related(rel_type="sibling", uid=B))
    plan = MergePlan([a, b], region="GB").to_json()
    assert all(B not in it["key"] for it in plan["lists"]["related"])


def test_commit_archives_repoints_and_prunes(cards, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ROOT", tmp_path)
    monkeypatch.setitem(server._state, "cards", list(cards))
    server._autosave_checkpoint()                      # materialise contacts/ files
    cdir = tmp_path / "cards-master" / "contacts"
    assert len(list(cdir.glob("*.vcf"))) == 3

    prev = server._api_merge_preview({"uids": [A, B], "primary_uid": A})
    assert prev["ok"] and prev["plan"]["primary"] == A

    res = server._api_merge_commit({
        "uids": [A, B], "primary_uid": A,
        "choices": {"scalars": {"bday": "2016-05-28"}},
    })
    assert res["ok"], res
    assert res["relinked"] == 1

    remaining = server._state["cards"]
    assert len(remaining) == 2
    survivor = by_uid(remaining, A)
    parent = by_uid(remaining, P)
    assert survivor.bday == "2016-05-28"
    assert B in survivor.external_uids
    assert survivor.addresses and survivor.addresses[0].street == "1 Test Street"
    assert any(r.uid == P for r in survivor.related)
    assert [r.uid for r in parent.related] == [A]       # repointed, not dangling

    # absorbed card's file is gone; archive holds BOTH originals incl. the unpicked BDAY
    assert len(list(cdir.glob("*.vcf"))) == 2
    archive = (tmp_path / res["archive"]).read_text(encoding="utf-8")
    assert archive.count("BEGIN:VCARD") == 2
    assert "20160527" in archive.replace("-", "")


def test_repoint_links_dedupes(cards):
    from vcard_normalizer.model import Related
    a, p = by_uid(cards, A), by_uid(cards, P)
    p.related = [Related(rel_type="child", uid=A), Related(rel_type="child", uid=B)]
    assert repoint_links([a, p], a, {B}) == 1
    assert [r.uid for r in p.related] == [A]


def test_auto_gender_endpoint(cards, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ROOT", tmp_path)
    for c in cards:
        c.gender = None
    monkeypatch.setitem(server._state, "cards", list(cards))
    res = server._api_auto_gender({})
    assert res["ok"] and res["changed"] == 3           # 2× Master → M, Mrs → F
    assert by_uid(cards, P).gender == "F"
