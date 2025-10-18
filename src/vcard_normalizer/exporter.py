from __future__ import annotations
from typing import List
from pathlib import Path
import vobject
from .model import Card

def export_vcards(cards: List[Card], path: Path, target_version: str = "4.0") -> int:
    # sort by FN (then N) for stability
    cards_sorted = sorted(cards, key=lambda c: (c.fn or "", c.n or ""))
    lines: list[str] = []
    for c in cards_sorted:
        v = vobject.vCard()
        v.add('version')
        v.version.value = target_version
        fn = c.fn or c.n or "Unnamed"
        v.add('fn'); v.fn.value = fn
        if c.n:
            try:
                v.add('n'); v.n.value = c.n
            except Exception:
                pass
        for e in sorted(set(c.emails)):
            it = v.add('email'); it.value = e; it.type_param = 'INTERNET'
        for t in sorted(set(c.tels)):
            it = v.add('tel'); it.value = t
        if c.org:
            try:
                it = v.add('org'); it.value = [c.org]
            except Exception:
                pass
        if c.title:
            it = v.add('title'); it.value = c.title
        if c.bday:
            it = v.add('bday'); it.value = c.bday
        if c.uid:
            it = v.add('uid'); it.value = c.uid
        it = v.add('prodid'); it.value = "-//vcard-normalizer//EN"
        it = v.add('rev'); it.value = vobject.vcard.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(v.serialize())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return len(cards_sorted)
