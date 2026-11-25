"""Auto-clean scan and name-fix wizard must agree on 'no first/last name split'."""
from __future__ import annotations

from vcard_normalizer import server
from vcard_normalizer.model import Card, NameComponents


def _c(fn, given="", family="", kind="individual", **extra):
    c = Card(raw=None, fn=fn, name=NameComponents(given=given, family=family), uid=fn, kind=kind)
    for k, v in extra.items():
        setattr(c, k, v)
    return c


def _load(cards):
    server._state["cards"] = cards


def test_scan_and_wizard_use_the_same_rule(monkeypatch):
    cards = [
        _c("Freddie"),                                   # needs split
        _c("Mr Smith", family="Smith"),                  # fine
        _c("Ann Jones", x_ios_given="Ann", x_ios_family="Jones"),  # already fixed via wizard
        _c("Acme Ltd", kind="org"),                       # org — never flagged
        _c("Book Club", kind="group"),                    # group — never flagged
    ]
    _load(cards)
    scan = server._api_auto_clean_scan({})
    g = scan["groups"]["no_name_components"]
    wiz = server._api_apple_name_unset({})
    assert g["count"] == wiz["total"] == 1
    assert g["indices"] == [c["_idx"] for c in wiz["cards"]] == [0]
    assert g["review"] == "name_fix"


def test_wizard_fix_clears_scan_issue(monkeypatch):
    monkeypatch.setattr(server, "_autosave_checkpoint", lambda: None)
    _load([_c("Freddie Hunter")])
    assert server._api_auto_clean_scan({})["groups"]["no_name_components"]["count"] == 1
    assert server._api_set_structured_name({"idx": 0, "given": "Freddie", "family": "Hunter"})["ok"]
    assert server._api_auto_clean_scan({})["groups"]["no_name_components"]["count"] == 0


def test_fixable_groups_stay_compact():
    _load([_c("Freddie")])
    groups = server._api_auto_clean_scan({})["groups"]
    assert "indices" not in groups["phones_unformatted"]
    assert groups["uncategorised"]["review"] == "no_category"
