"""
print_modules — pluggable printer/label-format support for vCard Studio
========================================================================

This package auto-discovers every Python module in this directory that
exposes the required print-module interface.  The core label engine in
server.py calls get_all_modules() at runtime — no registration step is
needed; simply drop a new .py file here and restart.

Required module-level attributes
---------------------------------
PRINTER_ID   : str            Unique snake_case identifier  (e.g. "brother_ql820nwb")
PRINTER_NAME : str            Human-readable name           (e.g. "Brother QL-820NWB")
PRINTER_DESC : str            One-line description shown in the UI
LABEL_PROFILES : list[dict]   One or more label profile dicts (see below)
PRINT_STEPS  : list[str]      Ordered print-dialog instructions (HTML allowed)

Optional module-level attributes
----------------------------------
DEFAULT_PROFILE_ID : str      Profile id to pre-select (defaults to first profile)

Label profile dict keys
------------------------
id          str   Unique identifier within this module   (e.g. "DK22205")
name        str   Display name in the UI dropdown
page_css    str   CSS @page rule content  (size + margins)
label_css   str   CSS for each .label div
name_size   str   CSS font-size for the recipient name line
hint        str   Short instruction shown next to the print button
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REQUIRED = ("PRINTER_ID", "PRINTER_NAME", "PRINTER_DESC", "LABEL_PROFILES", "PRINT_STEPS")


def get_all_modules() -> list[dict[str, Any]]:
    """Return a list of dicts describing every valid print module found."""
    import logging
    log = logging.getLogger(__name__)
    results = []
    pkg_dir = Path(__file__).parent
    log.info("print_modules: scanning %s", pkg_dir)

    for py_file in sorted(pkg_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        modname = py_file.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"vcard_normalizer.print_modules.{modname}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            log.warning("print_modules: failed to load %s: %s", modname, exc)
            continue

        missing = [a for a in _REQUIRED if not hasattr(mod, a)]
        if missing:
            log.warning("print_modules: %s missing attributes: %s", modname, missing)
            continue

        log.info("print_modules: loaded %s (%s)", modname, mod.PRINTER_NAME)
        results.append({
            "printer_id":      mod.PRINTER_ID,
            "printer_name":    mod.PRINTER_NAME,
            "printer_desc":    mod.PRINTER_DESC,
            "profiles":        mod.LABEL_PROFILES,
            "print_steps":     mod.PRINT_STEPS,
            "default_profile": getattr(mod, "DEFAULT_PROFILE_ID", mod.LABEL_PROFILES[0]["id"]),
        })

    results.sort(key=lambda m: m["printer_name"])
    log.info("print_modules: %d module(s) found", len(results))
    return results


def get_profile(printer_id: str, profile_id: str) -> dict | None:
    """Return a single label profile dict, or None if not found."""
    for mod_info in get_all_modules():
        if mod_info["printer_id"] == printer_id:
            for p in mod_info["profiles"]:
                if p["id"] == profile_id:
                    return p
    return None
