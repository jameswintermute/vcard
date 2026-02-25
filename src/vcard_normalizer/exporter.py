from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import vobject

from .model import Address, Card


def _address_to_vobject(v: vobject.vCard, a: Address) -> None:
    try:
        adr = v.add("adr")
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
        pass


def _build_name(raw_n: str) -> vobject.vcard.Name | None:
    """Convert a raw N string like 'Smith;John;;;' into a vobject Name object.

    The N field in vCard is semicolon-separated:
        family ; given ; additional ; prefix ; suffix
    Some exports store only a plain string with no semicolons — we handle that
    too by treating the whole thing as the family name.
    """
    try:
        parts = raw_n.split(";")
        # Pad to 5 fields
        while len(parts) < 5:
            parts.append("")
        return vobject.vcard.Name(
            family=parts[0],
            given=parts[1],
            additional=parts[2],
            prefix=parts[3],
            suffix=parts[4],
        )
    except Exception:
        return None


def export_vcards(cards: list[Card], path: Path, target_version: str = "4.0") -> int:
    """Serialise cards to a single VCF file, sorted alphabetically by FN then N.

    We build each output vCard entirely from the clean, parsed Card fields —
    never touching card.raw — so malformed source data cannot cause serialisation
    errors.
    """
    cards_sorted = sorted(cards, key=lambda c: (c.fn or "", c.n or ""))
    lines: list[str] = []
    skipped = 0

    for c in cards_sorted:
        try:
            v = vobject.vCard()

            # VERSION
            v.add("version").value = target_version

            # FN (required)
            fn = c.fn or c.n or "Unnamed"
            v.add("fn").value = fn

            # N (structured name) — rebuild from string, never pass raw vobject value
            if c.n:
                name_obj = _build_name(c.n)
                if name_obj is not None:
                    n_prop = v.add("n")
                    n_prop.value = name_obj

            # EMAIL
            for e in sorted(set(c.emails)):
                it = v.add("email")
                it.value = e
                it.type_param = "INTERNET"

            # TEL
            for t in sorted(set(c.tels)):
                it = v.add("tel")
                it.value = t

            # ORG
            if c.org:
                try:
                    v.add("org").value = [c.org]
                except Exception:
                    pass

            # TITLE
            if c.title:
                v.add("title").value = c.title

            # BDAY
            if c.bday:
                v.add("bday").value = c.bday

            # UID
            if c.uid:
                v.add("uid").value = c.uid

            # KIND (vCard 4.0 only)
            if c.kind and target_version == "4.0":
                v.add("kind").value = c.kind

            # ADR — rebuilt from our parsed Address objects
            for a in c.addresses:
                _address_to_vobject(v, a)

            # CATEGORIES
            if c.categories:
                v.add("categories").value = sorted(set(c.categories))

            # PRODID + REV
            v.add("prodid").value = "-//vcard-normalizer//EN"
            v.add("rev").value = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            lines.append(v.serialize())

        except Exception as exc:
            # Log and skip any card that still fails — never crash the whole run
            label = c.fn or c.org or "Unnamed"
            import logging
            logging.getLogger(__name__).warning(
                "Skipped contact %r during export: %s", label, exc
            )
            skipped += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")

    written = len(cards_sorted) - skipped
    if skipped:
        import logging
        logging.getLogger(__name__).warning(
            "Export complete: %d written, %d skipped due to errors", written, skipped
        )
    return written
