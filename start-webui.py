#!/usr/bin/env python3
"""vcard Studio — Browser UI.  Run with:  python3 start-webui.py"""
import sys
import os
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir    = os.path.join(script_dir, "src")

sys.path.insert(0, src_dir)
os.environ["PYTHONPATH"] = src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")
os.chdir(script_dir)

from vcard_normalizer.server import main
main()
