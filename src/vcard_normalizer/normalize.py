from __future__ import annotations

import re

import vobject

from .model import Address, Card, NameComponents, Related

# Properties that carry photo/image data — always stripped.
_PHOTO_PROPS = frozenset({"PHOTO", "LOGO", "SOUND"})


def _get_text(v, default=None):
    try:
        return str(v.value).strip()
    except Exception:
        return default


def _parse_addresses(vc: vobject.base.Component) -> list[Address]:
    addresses: list[Address] = []
    for adr in getattr(vc, "adr_list", []):
        try:
            val = adr.value
            addresses.append(
                Address(
                    po_box=val.box or None,
                    extended=val.extended or None,
                    street=val.street or None,
                    locality=val.city or None,
                    region=val.region or None,
                    postal_code=val.code or None,
                    country=val.country or None,
                )
            )
        except Exception:
            pass
    return addresses


def strip_photos(vc: vobject.base.Component) -> int:
    """Remove any PHOTO/LOGO/SOUND children from the raw vobject. Returns count removed."""
    to_remove = [
        child for child in list(vc.getChildren())
        if getattr(child, "name", "").upper() in _PHOTO_PROPS
    ]
    for child in to_remove:
        vc.remove(child)
    return len(to_remove)


def normalize_cards(
    vcards: list[tuple[vobject.base.Component, str]],
) -> list[Card]:
    """Convert (vobject_component, source_label) pairs into Card objects.

    Strips photos immediately and records the source filename on each card
    so the report can show where each contact came from.
    """
    out: list[Card] = []
    for vc, source_label in vcards:
        fn = _get_text(getattr(vc, "fn", None))

        # Parse structured N field into NameComponents
        name = NameComponents()
        if getattr(vc, "n", None):
            try:
                nval = vc.n.value
                # vobject gives us a Name object with attributes
                name.family     = (nval.family     or "").strip()
                name.given      = (nval.given      or "").strip()
                name.additional = (nval.additional or "").strip()
                name.prefix     = (nval.prefix     or "").strip()
                name.suffix     = (nval.suffix     or "").strip()
            except Exception:
                # Fallback: parse raw string
                raw = _get_text(getattr(vc, "n", None)) or ""
                if raw:
                    name = NameComponents.from_vcard_str(raw)

        emails: list[str] = []
        for e in getattr(vc, "email_list", []):
            val = _get_text(e)
            if val:
                emails.append(val.lower())

        tels: list[str] = []
        for t in getattr(vc, "tel_list", []):
            val = re.sub(r"\s+", "", _get_text(t, ""))
            if val:
                tels.append(val)

        org = None
        if getattr(vc, "org", None):
            try:
                org = " ".join([p for p in vc.org.value if p]).strip()
            except Exception:
                pass

        title = _get_text(getattr(vc, "title", None))
        bday = _get_text(getattr(vc, "bday", None))
        anniversary = _get_text(getattr(vc, "anniversary", None))
        uid = _get_text(getattr(vc, "uid", None))
        rev = _get_text(getattr(vc, "rev", None))
        addresses = _parse_addresses(vc)

        # Parse RELATED (vCard 4.0) — links to other contacts
        related: list[Related] = []
        for rel_prop in getattr(vc, "related_list", []):
            try:
                rel_type = "contact"
                if hasattr(rel_prop, "type_param"):
                    rel_type = str(rel_prop.type_param).lower()
                val = str(rel_prop.value).strip()
                if val.startswith("urn:uuid:"):
                    related.append(Related(rel_type=rel_type, uid=val[9:]))
                elif val:
                    related.append(Related(rel_type=rel_type, text=val))
            except Exception:
                pass

        # Parse CATEGORIES — may be a list (vCard 4.0) or a comma-separated string
        categories: list[str] = []
        for cat_prop in getattr(vc, "categories_list", []):
            try:
                val = cat_prop.value
                if isinstance(val, (list, tuple)):
                    categories.extend(v.strip() for v in val if v.strip())
                elif isinstance(val, str):
                    categories.extend(v.strip() for v in val.split(",") if v.strip())
            except Exception:
                pass
        categories = sorted(set(categories))

        photo_count = strip_photos(vc)

        note = _get_text(getattr(vc, "note", None))

        card = Card(
            raw=vc,
            fn=fn,
            name=name,
            emails=emails,
            tels=tels,
            org=org,
            title=title,
            bday=bday,
            anniversary=anniversary,
            uid=uid,
            rev=rev,
            addresses=addresses,
            categories=categories,
            related=related,
            note=note,
            _source_files=[source_label],
        )
        if photo_count:
            card.log_change(f"Stripped {photo_count} photo/logo/sound property(ies)")

        out.append(card)
    return out


def strip_proprietary(card: Card) -> Card:
    from .proprietary import DefaultStripper
    return DefaultStripper().strip(card)
