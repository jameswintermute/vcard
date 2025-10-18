from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # not expected on Ubuntu 24.04


@dataclass
class Paths:
    root: Path
    raw_dir: Path
    clean_dir: Path
    var_dir: Path
    local_dir: Path
    conf_file: Path


@dataclass
class Settings:
    owner_name: str = "James"
    default_region: str = "GB"


DEFAULT_CONF = """# vcard-normalizer local config (TOML)
owner_name = "James"
default_region = "GB"
"""


def ensure_workspace(base: Path | None = None) -> tuple[Paths, Settings]:
    root = Path(base or os.getcwd())
    raw = root / "cards-raw"
    clean = root / "cards-clean"
    var = root / "var"
    local = root / "local"
    conf = local / "vcard.conf"

    for d in (raw, clean, var, local):
        d.mkdir(parents=True, exist_ok=True)

    if not conf.exists():
        conf.write_text(DEFAULT_CONF, encoding="utf-8")

    settings = Settings()
    try:
        if tomllib is not None:
            data = tomllib.loads(conf.read_text(encoding="utf-8"))
            settings.owner_name = str(data.get("owner_name", settings.owner_name))
            settings.default_region = str(data.get("default_region", settings.default_region))
    except Exception:
        # if config is malformed, fall back to defaults silently
        pass

    return (
        Paths(root=root, raw_dir=raw, clean_dir=clean, var_dir=var, local_dir=local, conf_file=conf),
        settings,
    )
