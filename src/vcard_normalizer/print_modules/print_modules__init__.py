"""
print_modules — pluggable printer/label-format support for vCard Studio
========================================================================

Drop a .py file in this directory and restart — it is auto-discovered.

Required module-level attributes:
  PRINTER_ID, PRINTER_NAME, PRINTER_DESC, LABEL_PROFILES, PRINT_STEPS

Optional:
  DEFAULT_PROFILE_ID
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_REQUIRED = ("PRINTER_ID", "PRINTER_NAME", "PRINTER_DESC", "LABEL_PROFILES", "PRINT_STEPS")


def get_all_modules() -> list[dict[str, Any]]:
    """Return a list of dicts describing every valid print module found.

    Uses exec() into a fresh namespace — avoids all import machinery issues
    (pkgutil, importlib caching, pycache conflicts).
    """
    import logging
    log = logging.getLogger(__name__)
    results = []
    pkg_dir = Path(__file__).parent

    for py_file in sorted(pkg_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        ns: dict = {}
        try:
            exec(compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec"), ns)
        except Exception as exc:
            log.warning("print_modules: failed to exec %s: %s", py_file.name, exc)
            continue

        missing = [a for a in _REQUIRED if a not in ns]
        if missing:
            log.warning("print_modules: %s missing: %s", py_file.name, missing)
            continue

        results.append({
            "printer_id":      ns["PRINTER_ID"],
            "printer_name":    ns["PRINTER_NAME"],
            "printer_desc":    ns["PRINTER_DESC"],
            "profiles":        ns["LABEL_PROFILES"],
            "print_steps":     ns["PRINT_STEPS"],
            "default_profile": ns.get("DEFAULT_PROFILE_ID", ns["LABEL_PROFILES"][0]["id"]),
        })
        log.info("print_modules: loaded %s (%s)", py_file.name, ns["PRINTER_NAME"])

    results.sort(key=lambda m: m["printer_name"])
    print(f"[print_modules] found {len(results)}: {[m['printer_id'] for m in results]}", flush=True)
    return results


def get_profile(printer_id: str, profile_id: str) -> dict | None:
    """Return a single label profile dict, or None if not found."""
    for mod_info in get_all_modules():
        if mod_info["printer_id"] == printer_id:
            for p in mod_info["profiles"]:
                if p["id"] == profile_id:
                    return p
    return None
