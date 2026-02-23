from __future__ import annotations

from pathlib import Path

import vobject


def read_vcards_from_files(
    paths: list[Path],
) -> list[tuple[vobject.base.Component, str]]:
    """Parse all .vcf files and return (vobject_component, source_label) pairs.

    The source_label is the filename stem (e.g. 'icloud', 'protonmail') so the
    rest of the pipeline can report where each card came from.
    """
    results: list[tuple[vobject.base.Component, str]] = []
    for p in paths:
        label = p.stem  # e.g. "icloud" from "icloud.vcf"
        with p.open("r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        for vc in vobject.readComponents(data):
            if vc.name.upper() == "VCARD":
                results.append((vc, label))
    return results


def collect_merge_sources(merge_dir: Path) -> list[Path]:
    """Return all .vcf files found directly inside merge_dir, sorted by name."""
    if not merge_dir.is_dir():
        return []
    return sorted(p for p in merge_dir.iterdir() if p.suffix.lower() == ".vcf")
