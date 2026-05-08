#!/usr/bin/env python3
"""vcard Studio — Browser UI.  Run with:  python3 start-webui.py"""
import sys
import os
import shutil
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir    = os.path.join(script_dir, "src")

# Clear __pycache__ so updated .py files are always used
for cache_dir in Path(src_dir).rglob("__pycache__"):
    shutil.rmtree(cache_dir, ignore_errors=True)

# Force the local src/ to be first — must come before any editable install path
if src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)
os.environ["PYTHONPATH"] = src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")
os.chdir(script_dir)

# Verify we're loading from the right place
import importlib, importlib.util
spec = importlib.util.find_spec("vcard_normalizer.server")
expected = os.path.join(src_dir, "vcard_normalizer", "server.py")
if spec and os.path.abspath(spec.origin) != os.path.abspath(expected):
    print(f"\n  WARNING: loading server from unexpected location:")
    print(f"    expected: {expected}")
    print(f"    got:      {spec.origin}")
    print(f"  Forcing correct path...\n")
    # Remove any other vcard_normalizer from path
    sys.path = [p for p in sys.path if "vcard_normalizer" not in p and (p == src_dir or "vcard" not in p.lower() or p == src_dir)]
    sys.path.insert(0, src_dir)

# ── Dependency check ──────────────────────────────────────────────────────────
_REQUIRED = {
    "vobject":      "vobject",
    "rapidfuzz":    "rapidfuzz",
    "phonenumbers": "phonenumbers",
}
_missing = []
for _import_name, _pkg_name in _REQUIRED.items():
    try:
        __import__(_import_name)
    except ImportError:
        _missing.append(_pkg_name)

if _missing:
    print("\n  ✗  vCard Studio cannot start — missing Python packages:\n")
    for _pkg in _missing:
        print(f"       • {_pkg}")
    print("\n  Install them with:\n")
    import subprocess as _sp
    _test = _sp.run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "vobject"],
        capture_output=True, text=True
    )
    _flag = " --break-system-packages" if "externally-managed" in _test.stderr else ""
    print(f"       pip3 install {' '.join(_missing)}{_flag}")
    print()
    sys.exit(1)
# ── End dependency check ───────────────────────────────────────────────────────

from vcard_normalizer.server import main
main()
