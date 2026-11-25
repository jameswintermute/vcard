"""Stale-data loop: country codes derived from the visible name; purge tool."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from vcard_normalizer.countries import country_code_for, effective_apple_code
from vcard_normalizer.exporter import _serialise_one_apple
from vcard_normalizer.master import load_master, save_master
from vcard_normalizer.model import Address, Card, NameComponents

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("purge_stale", ROOT / "tools" / "purge_stale.py")
purge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(purge)


def _card(uid, *addresses):
    return Card(raw=None, fn=f"Test {uid}", name=NameComponents(given="Test", family=uid),
                uid=uid, addresses=list(addresses))


def test_country_names_map_to_codes():
    assert country_code_for("United Kingdom") == "gb"
    assert country_code_for("united states") == "us"
    assert country_code_for("USA") == "us"
    assert country_code_for("Poland") == "pl"
    assert country_code_for("Narnia") == ""


def test_stale_stored_code_never_overrides_the_visible_name():
    assert effective_apple_code("United States", "au") == "us"
    assert effective_apple_code("", "gb") == "gb"
    assert effective_apple_code("Narnia", "au") == ""


def test_apple_export_writes_code_derived_from_country_name():
    c = _card("x", Address(street="46 Example Blvd", locality="Springfield", postal_code="SC 29401",
                           country="United States", apple_country_code="au"))
    text = _serialise_one_apple(c).lower()
    assert "x-abadr:us" in text and "x-abadr:au" not in text


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_purge_dry_run_then_apply(tmp_path, monkeypatch):
    edited = Address(street="Mill House\nMill Lane", locality="Send", postal_code="GU23 7ZZ",
                     country="United Kingdom", apple_country_code="gb")
    stale = Address(street="Mill HouseMill Lane", locality="Send", postal_code="gu237zz",
                    country="United Kingdom", pref=True)
    second_home = Address(street="1 Rue Exemple", locality="Paris", postal_code="75001", country="France")
    wrong_code = Address(street="5 Example Rd", postal_code="SC 29401", country="United States",
                         apple_country_code="au")
    save_master([_card("a", edited, stale, second_home), _card("b", wrong_code)], root=tmp_path)
    vcf = tmp_path / "cards-master" / "master.vcf"
    before = _sha(vcf)

    assert purge.main(["--root", str(tmp_path), "--out", str(tmp_path / "r.html")]) == 0
    assert _sha(vcf) == before                                   # dry run wrote nothing

    monkeypatch.setattr(purge, "_server_running", lambda: False)
    assert purge.main(["--root", str(tmp_path), "--apply", "--out", str(tmp_path / "r2.html")]) == 0
    cards, _ = load_master(tmp_path)
    a = next(c for c in cards if c.fn == "Test a")
    b = next(c for c in cards if c.fn == "Test b")
    assert [ad.postal_code for ad in a.addresses] == ["GU23 7ZZ", "75001"]   # stale copy gone, 2nd home kept
    assert a.addresses[0].street == "Mill House\nMill Lane"                  # edited one kept
    assert b.addresses[0].apple_country_code == "us"                          # code follows the name
    backups = list((tmp_path / "var" / "backups").iterdir())
    assert len(backups) == 1 and (backups[0] / "master.vcf").exists()


def test_purge_refuses_while_server_running(tmp_path, monkeypatch):
    save_master([_card("a", Address(postal_code="X1 1AA"), Address(postal_code="x11aa"))], root=tmp_path)
    monkeypatch.setattr(purge, "_server_running", lambda: True)
    before = _sha(tmp_path / "cards-master" / "master.vcf")
    assert purge.main(["--root", str(tmp_path), "--apply", "--out", str(tmp_path / "r.html")]) == 2
    assert _sha(tmp_path / "cards-master" / "master.vcf") == before


def test_edit_form_resets_stored_code_when_country_changes(monkeypatch):
    from vcard_normalizer import server
    c = Card(raw=None, fn="Mr John Example", name=NameComponents(given="John", family="Example"), uid="u1",
             addresses=[Address(street="46 Example Blvd", postal_code="SC 29401",
                                country="Australia", apple_country_code="au")])
    monkeypatch.setitem(server._state, "cards", [c])
    monkeypatch.setattr(server, "_autosave_checkpoint", lambda *a, **k: None, raising=False)
    body = {"index": 0, "fn": "Mr John Example", "street": "46 Example Blvd",
            "postal": "SC 29401", "country": "United States"}
    assert server._api_full_update_card(body)["ok"]
    assert server._state["cards"][0].addresses[0].apple_country_code == "us"
    body["street"] = "46 Example Boulevard"
    server._api_full_update_card(body)
    assert server._state["cards"][0].addresses[0].apple_country_code == "us"
