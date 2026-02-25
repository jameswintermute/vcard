import types
from pathlib import Path

from vcard_normalizer.config import first_run_setup


def test_first_run_creates_conf(tmp_path: Path):
    conf = tmp_path / "local" / "vcard.conf"
    settings = types.SimpleNamespace(first_run=True)

    first_run_setup(settings, conf)

    assert conf.exists()
    txt = conf.read_text()
    assert "first_run = false" in txt
    assert "cards_raw_dir = cards-raw" in txt
    assert "cards_clean_dir = cards-clean" in txt
    # In-memory flag flipped
    assert settings.first_run is False
