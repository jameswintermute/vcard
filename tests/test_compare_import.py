"""tools/compare_import.py must be strictly read-only and classify correctly."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compare_import", ROOT / "tools" / "compare_import.py")
compare_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_import)

MASTER = """BEGIN:VCARD
VERSION:3.0
UID:vcard-studio-a
FN:Alice Example
N:Example;Alice;;;
EMAIL:alice@example.com
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:vcard-studio-d
FN:Laptop Only
N:Only;Laptop;;;
END:VCARD
"""
IMPORT = """BEGIN:VCARD
VERSION:3.0
UID:icloud-x
FN:Alice Example
N:Example;Alice;;;
EMAIL:alice@example.com
EMAIL:alice.new@example.com
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:icloud-new
FN:Dave New
N:New;Dave;;;
EMAIL:dave@example.com
END:VCARD
"""


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_compare_is_read_only_and_reports(tmp_path, capsys):
    (tmp_path / "cards-master").mkdir()
    master = tmp_path / "cards-master" / "master.vcf"
    master.write_text(MASTER, encoding="utf-8")
    imp = tmp_path / "import.vcf"
    imp.write_text(IMPORT, encoding="utf-8")
    before = {p: _sha(p) for p in (master, imp)}
    listing = sorted(p.name for p in (tmp_path / "cards-master").iterdir())

    report = tmp_path / "report.html"
    compare_import.main([str(imp), "--root", str(tmp_path), "--out", str(report)])

    assert {p: _sha(p) for p in (master, imp)} == before
    assert sorted(p.name for p in (tmp_path / "cards-master").iterdir()) == listing
    out = capsys.readouterr().out
    assert "new on import            : 1" in out
    assert "matched, with differences: 1" in out
    assert "laptop-only              : 1" in out
    text = report.read_text(encoding="utf-8")
    assert "Dave New" in text and "alice.new@example.com" in text
