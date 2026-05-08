#!/usr/bin/env python3
"""vCard Studio — Browser UI.  Run with:  python3 start-webui.py

On first run this script creates a .venv/ in the project folder, installs all
dependencies into it, then re-launches itself inside the venv automatically.
Subsequent runs skip straight to the app.  No manual pip or sudo required.
"""
import sys
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT    = Path(__file__).resolve()
ROOT      = SCRIPT.parent
VENV_DIR  = ROOT / ".venv"
PACKAGES  = ["vobject", "rapidfuzz", "phonenumbers"]

# ── 1. Venv bootstrap (skipped when already inside the venv) ──────────────────
def _inside_venv() -> bool:
    return Path(sys.executable).is_relative_to(VENV_DIR)

if not _inside_venv():
    venv_python = VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    # Create venv if missing
    if not venv_python.exists():
        print("  vCard Studio — first run setup")
        print("  Creating virtual environment (.venv/)…")
        result = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
        if result.returncode != 0:
            print("\n  ✗  Failed to create virtual environment.")
            print("     Make sure python3-venv is installed:\n")
            print("       sudo apt install python3-venv\n")
            sys.exit(1)
        print("  ✓  Virtual environment created")

    # Install / upgrade packages if any are missing
    check = subprocess.run(
        [str(venv_python), "-c",
         f"import {', '.join(p.split('[')[0] for p in PACKAGES)}"],
        capture_output=True
    )
    if check.returncode != 0:
        print(f"  Installing dependencies: {', '.join(PACKAGES)} …")
        result = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade"] + PACKAGES
        )
        if result.returncode != 0:
            print("\n  ✗  Failed to install dependencies.")
            print("     Try manually:\n")
            print(f"       {venv_python} -m pip install {' '.join(PACKAGES)}\n")
            sys.exit(1)
        print("  ✓  Dependencies installed")

    # Re-exec inside the venv — replaces this process
    print("  Starting vCard Studio…")
    os.execv(str(venv_python), [str(venv_python), str(SCRIPT)] + sys.argv[1:])
    sys.exit(0)  # unreachable, but explicit

# ── 2. Running inside venv from here on ───────────────────────────────────────

script_dir = str(ROOT)
src_dir    = str(ROOT / "src")

# Clear __pycache__ so updated .py files are always used
for cache_dir in Path(src_dir).rglob("__pycache__"):
    shutil.rmtree(cache_dir, ignore_errors=True)

# Force the local src/ to be first
if src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)
os.environ["PYTHONPATH"] = src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")
os.chdir(script_dir)

# Verify we're loading from the right place
import importlib.util
spec = importlib.util.find_spec("vcard_normalizer.server")
expected = os.path.join(src_dir, "vcard_normalizer", "server.py")
if spec and os.path.abspath(spec.origin) != os.path.abspath(expected):
    print(f"\n  WARNING: loading server from unexpected location:")
    print(f"    expected: {expected}")
    print(f"    got:      {spec.origin}\n")
    sys.path = [p for p in sys.path if "vcard_normalizer" not in p and
                (p == src_dir or "vcard" not in p.lower() or p == src_dir)]
    sys.path.insert(0, src_dir)

from vcard_normalizer.server import main
main()
