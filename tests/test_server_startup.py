"""Regression: the browser-launch helper inside main() must see the module-level
subprocess import. A function-level `import subprocess` anywhere in main() makes
the name local to main(), so the nested _open() raised NameError on a normal start."""
from __future__ import annotations

import symtable
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "src" / "vcard_normalizer" / "server.py"


def _main_table():
    top = symtable.symtable(SERVER.read_text(encoding="utf-8"), str(SERVER), "exec")
    return next(t for t in top.get_children() if t.get_name() == "main")


def test_subprocess_is_not_local_to_main():
    assert not _main_table().lookup("subprocess").is_local()


def test_open_helper_uses_module_level_names():
    main = _main_table()
    opener = next(t for t in main.get_children() if t.get_name() == "_open")
    for name in ("subprocess", "shutil", "sys", "webbrowser"):
        if name in opener.get_identifiers():
            assert opener.lookup(name).is_global(), name
