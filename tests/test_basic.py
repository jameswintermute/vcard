from pathlib import Path
from vcard_normalizer.exporter import export_vcards
from vcard_normalizer.model import Card

def test_export(tmp_path: Path):
    c1 = Card(raw=None, fn="Alice", emails=["alice@example.com"], tels=["+4412345678"])
    out = tmp_path / "out.vcf"
    n = export_vcards([c1], out)
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "FN:Alice" in text
