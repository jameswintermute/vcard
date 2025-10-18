from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import vobject

from .model import Address, Card


def _address_to_vobject(v: vobject.vCard, a: Address) -> None:
    adr = v.add("adr")
    try:
        adr.value = vobject.vcard.Address(
            box=a.po_box or "",
            extended=a.extended or "",
            street=a.street or "",
            city=a.locality or "",
            region=a.region or "",
            code=a.postal_code or "",
            country=a.country or "",
        )
    except Exception:
        # If anything goes wrong, skip this address gracefully
        pass


def export_vcards(cards: list[Card], path: Path, target_version: str = "4.0") -> int:
    """Serialize cards to a single VCF, sorted by FN then N."""
    cards_sorted = sorted(cards, key=lambda c: (c.fn or "", c.n or ""))
    lines: list[str] = []

    for c in cards_sorted:
        v = vobject.vCard()

        v.add("version")
        v.version.value = target_version

        fn = c.fn or c.n or "Unnamed"
        v.add("fn")
        v.fn.value = fn

        if c.n:
            try:
                v.add("n")
                v.n.value = c.n
            except Exception:
                pass

        for e in sorted(set(c.emails)):
            it = v.add("email")
            it.value = e
            it.type_param = "INTERNET"

        for t in sorted(set(c.tels)):
            it = v.add("tel")
            it.value = t

        if c.org:
            try:
                it = v.add("org")
                it.value = [c.org]
            except Exception:
                pass

        if c.title:
            it = v.add("title")
            it.value = c.title

        if c.bday:
            it = v.add("bday")
            it.value = c.bday

        if c.uid:
            it = v.add("uid")
            it.value = c.uid

        if c.kind:
            it = v.add("kind")
            it.value = c.kind

        for a in c.addresses:
            _address_to_vobject(v, a)

        if c.categories:
            it = v.add("categories")
            it.value = list(sorted(set(c.categories)))

        it = v.add("prodid")
        it.value = "-//vcard-normalizer//EN"

        it = v.add("rev")
        it.value = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        lines.append(v.serialize())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return len(cards_sorted)
