from pathlib import Path
from vcard_normalizer.config import ensure_workspace


def test_ensure_workspace_creates_dirs(tmp_path: Path):
    """ensure_workspace creates the required folder structure."""
    paths, settings = ensure_workspace(tmp_path)

    assert paths.in_dir.exists(),    "cards-in/ should exist"
    assert paths.out_dir.exists(),   "cards-out/ should exist"
    assert paths.local_dir.exists(), "local/ should exist"
    assert paths.conf_file.exists(), "vcard.conf should be created"
    assert not (tmp_path / "cards-wip").exists(), "cards-wip/ should NOT be created"
    assert not (tmp_path / "cards-master").exists(), "cards-master/ created by master.py, not here"


def test_settings_defaults(tmp_path: Path):
    """Settings have sensible defaults."""
    _, settings = ensure_workspace(tmp_path)
    assert settings.owner_name == ""          # not hardcoded to "James"
    assert len(settings.default_region) == 2  # auto-detected, should be a 2-char code
