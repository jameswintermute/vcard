"""Lossless field-aware contact merging.

The central vCard Studio record is authoritative.  Incoming/provider records may
add information, but they never replace a populated master value wholesale.
Multi-valued fields are unioned and scalar conflicts are retained on the master
record and recorded in the in-session change log for review.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from .model import Address, Card, Related, TypedValue


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _union_strings(base: list[str], incoming: list[str], *, casefold: bool = True) -> tuple[list[str], bool]:
    out = list(base or [])
    seen = {(_norm(v) if casefold else v) for v in out if v}
    changed = False
    for value in incoming or []:
        if not value:
            continue
        key = _norm(value) if casefold else value
        if key not in seen:
            out.append(value)
            seen.add(key)
            changed = True
    return out, changed


def _merge_typed(base: list[TypedValue], incoming: list[TypedValue]) -> tuple[list[TypedValue], bool]:
    out = list(base or [])
    by_value = {_norm(tv.value): tv for tv in out if tv.value}
    changed = False
    for tv in incoming or []:
        if not tv.value:
            continue
        key = _norm(tv.value)
        existing = by_value.get(key)
        if existing is None:
            clone = TypedValue(value=tv.value, type=tv.type, label=tv.label, pref=tv.pref)
            out.append(clone)
            by_value[key] = clone
            changed = True
            continue
        if not existing.type and tv.type:
            existing.type = tv.type
            changed = True
        if not existing.label and tv.label:
            existing.label = tv.label
            changed = True
        if tv.pref and not existing.pref:
            existing.pref = True
            changed = True
    return out, changed


def _address_identity(a: Address) -> tuple[str, ...]:
    return tuple(
        _norm(v)
        for v in (
            a.po_box,
            a.extended,
            a.street,
            a.locality,
            a.region,
            a.postal_code,
            a.country,
        )
    )


def _merge_addresses(base: list[Address], incoming: list[Address]) -> tuple[list[Address], bool]:
    out = list(base or [])
    by_identity = {_address_identity(a): a for a in out}
    changed = False
    for addr in incoming or []:
        key = _address_identity(addr)
        existing = by_identity.get(key)
        if existing is None:
            clone = Address(**{f.name: getattr(addr, f.name) for f in fields(Address)})
            out.append(clone)
            by_identity[key] = clone
            changed = True
            continue
        for attr in ("type", "label", "apple_country_code"):
            if not getattr(existing, attr) and getattr(addr, attr):
                setattr(existing, attr, getattr(addr, attr))
                changed = True
        if addr.pref and not existing.pref:
            existing.pref = True
            changed = True
    return out, changed


def _related_identity(rel: Related) -> tuple[str, str, str]:
    return (_norm(rel.rel_type), _norm(rel.uid), _norm(rel.text))


def _merge_related(base: list[Related], incoming: list[Related]) -> tuple[list[Related], bool]:
    out = list(base or [])
    seen = {_related_identity(r) for r in out}
    changed = False
    for rel in incoming or []:
        key = _related_identity(rel)
        if key not in seen:
            out.append(Related(rel_type=rel.rel_type, uid=rel.uid, text=rel.text))
            seen.add(key)
            changed = True
    return out, changed


def _fill_scalar(base: Card, incoming: Card, attr: str, conflicts: list[str]) -> bool:
    current = getattr(base, attr, None)
    new = getattr(incoming, attr, None)
    if not current and new:
        setattr(base, attr, new)
        return True
    if current and new and _norm(str(current)) != _norm(str(new)):
        conflicts.append(attr)
    return False


def merge_cards_preserving_base(base: Card, incoming: Card, *, log_conflicts: bool = True) -> tuple[Card, bool]:
    """Merge *incoming* into *base* without reducing populated base data.

    The object in ``base`` is mutated and returned.  Scalar gaps are filled,
    multi-value fields are unioned, and scalar conflicts leave the master value
    untouched.  Returns ``(base, changed)``.
    """
    changed = False
    conflicts: list[str] = []

    # Structured name: fill individual missing components only.
    for attr in ("family", "given", "additional", "prefix", "suffix"):
        current = getattr(base.name, attr, "")
        new = getattr(incoming.name, attr, "")
        if not current and new:
            setattr(base.name, attr, new)
            changed = True
        elif current and new and _norm(current) != _norm(new):
            conflicts.append(f"name.{attr}")

    for attr in ("fn", "org", "title", "bday", "anniversary", "kind", "gender", "note", "x_ios_given", "x_ios_family"):
        changed |= _fill_scalar(base, incoming, attr, conflicts)

    base.emails, c = _union_strings(base.emails, incoming.emails)
    changed |= c
    base.tels, c = _union_strings(base.tels, incoming.tels)
    changed |= c
    base.categories, c = _union_strings(base.categories, incoming.categories)
    changed |= c
    base.nicknames, c = _union_strings(base.nicknames, incoming.nicknames)
    changed |= c
    base.external_uids, c = _union_strings(base.external_uids, incoming.external_uids, casefold=False)
    changed |= c
    base.member, c = _union_strings(base.member, incoming.member, casefold=False)
    changed |= c

    base.typed_emails, c = _merge_typed(base.typed_emails, incoming.typed_emails)
    changed |= c
    base.typed_tels, c = _merge_typed(base.typed_tels, incoming.typed_tels)
    changed |= c
    base.urls, c = _merge_typed(base.urls, incoming.urls)
    changed |= c
    base.addresses, c = _merge_addresses(base.addresses, incoming.addresses)
    changed |= c
    base.related, c = _merge_related(base.related, incoming.related)
    changed |= c

    # Ensure every plain email/tel has a typed counterpart, without fabricating a label.
    typed_email_values = {_norm(tv.value) for tv in base.typed_emails}
    for value in base.emails:
        if _norm(value) not in typed_email_values:
            base.typed_emails.append(TypedValue(value=value))
            typed_email_values.add(_norm(value))
            changed = True
    typed_tel_values = {_norm(tv.value) for tv in base.typed_tels}
    for value in base.tels:
        if _norm(value) not in typed_tel_values:
            base.typed_tels.append(TypedValue(value=value))
            typed_tel_values.add(_norm(value))
            changed = True

    # Keep canonical UID from the base.  Remember any different incoming UID as an alias.
    if not base.uid and incoming.uid:
        base.uid = incoming.uid
        changed = True
    elif base.uid and incoming.uid and base.uid != incoming.uid:
        aliases, c = _union_strings(base.external_uids, [incoming.uid], casefold=False)
        base.external_uids = aliases
        changed |= c

    # Merge provenance and user-quality waivers.
    base._source_files, c = _union_strings(base._source_files, incoming._source_files, casefold=False)
    changed |= c
    before_waived = set(base._waived or set())
    base._waived = before_waived | set(incoming._waived or set())
    changed |= base._waived != before_waived

    # Preserve arbitrary provider metadata without replacing keys already owned by master.
    for key, value in (incoming.props or {}).items():
        if key not in base.props:
            base.props[key] = value
            changed = True

    if changed:
        base.rev = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base.log_change("Merged additional data from imported/duplicate contact")
    if conflicts and log_conflicts:
        base.log_change("Import conflict retained master field(s): " + ", ".join(sorted(set(conflicts))))

    return base, changed


def card_richness(card: Card) -> int:
    """Broad information score used only for display/diagnostic decisions."""
    scalar_fields = (card.fn, card.org, card.title, card.bday, card.anniversary, card.kind, card.gender, card.note)
    name_parts = (card.name.family, card.name.given, card.name.additional, card.name.prefix, card.name.suffix)
    return (
        sum(bool(v) for v in scalar_fields)
        + sum(bool(v) for v in name_parts)
        + len(card.emails)
        + len(card.tels)
        + len(card.urls)
        + len(card.nicknames)
        + (2 * len(card.addresses))
        + len(card.categories)
        + len(card.related)
        + len(card.member)
    )
