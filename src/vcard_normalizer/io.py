from __future__ import annotations

from pathlib import Path

import vobject


def read_vcards_from_files(paths: list[Path]) -> list[vobject.base.Component]:
    cards: list[vobject.base.Component] = []
    for p in paths:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        for vc in vobject.readComponents(data):
            if vc.name.upper() == "VCARD":
                cards.append(vc)
    return cards
