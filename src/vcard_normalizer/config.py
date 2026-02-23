from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # py3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


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
    # Category rules: list of (category_name, [pattern, ...])
    # Patterns are plain substrings or "re:<regex>" strings.
    category_rules: list[tuple[str, list[str]]] = field(default_factory=list)


DEFAULT_CONF = """\
# vcard-normalizer local config (TOML)
owner_name = "James"
default_region = "GB"

# Category auto-tagging rules.
# Each [[category_rules]] block defines one category.
# 'patterns' are case-insensitive substrings matched against FN, ORG, TITLE, and emails.
# Prefix a pattern with "re:" to use a regular expression.
#
# Example:
# [[category_rules]]
# name = "Work"
# patterns = [" ltd", " plc", "re:@(?!gmail|yahoo)"]
#
# [[category_rules]]
# name = "School"
# patterns = ["school", "university", "college"]
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
    if tomllib is not None:
        try:
            data = tomllib.loads(conf.read_text(encoding="utf-8"))
            settings.owner_name = str(data.get("owner_name", settings.owner_name))
            settings.default_region = str(data.get("default_region", settings.default_region))
            # Parse [[category_rules]] array of tables
            raw_rules = data.get("category_rules", [])
            if isinstance(raw_rules, list):
                parsed: list[tuple[str, list[str]]] = []
                for entry in raw_rules:
                    if isinstance(entry, dict):
                        name = str(entry.get("name", "")).strip()
                        patterns = [str(p) for p in entry.get("patterns", [])]
                        if name:
                            parsed.append((name, patterns))
                settings.category_rules = parsed
        except Exception:
            # Malformed config → fall back to defaults silently
            pass

    return (
        Paths(root=root, raw_dir=raw, clean_dir=clean, var_dir=var, local_dir=local, conf_file=conf),
        settings,
    )


# ── Helpers + first-run setup ──────────────────────────────────────────────────

def _get_setting(settings: Any, name: str, default: Any = None) -> Any:
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _set_setting(settings: Any, name: str, value: Any = None) -> None:
    if isinstance(settings, dict):
        settings[name] = value
    else:
        setattr(settings, name, value)


def first_run_setup(settings: Any, conf_path: Path) -> None:
    """Idempotent first-run initializer."""
    conf_path = Path(conf_path)
    conf_path.parent.mkdir(parents=True, exist_ok=True)

    if not conf_path.exists():
        conf_path.write_text(
            "# vcard_normalizer local configuration\n"
            "first_run = false\n"
            "default_region = GB\n"
            "cards_raw_dir = cards-raw\n"
            "cards_clean_dir = cards-clean\n"
        )

    _set_setting(settings, "first_run", False)

