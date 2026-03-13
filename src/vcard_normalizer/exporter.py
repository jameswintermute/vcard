from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import vobject

from .model import Address, Card, NameComponents

PRODID = "-//vCard Studio//https://github.com/jameswintermute/vcard//EN"


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


def _name_to_vobject(name: NameComponents) -> vobject.vcard.Name | None:
    try:
        return vobject.vcard.Name(
            family=name.family,
            given=name.given,
            additional=name.additional,
            prefix=name.prefix,
            suffix=name.suffix,
        )
    except Exception:
        return None


def _serialise_one(c: Card, target_version: str = "4.0") -> str:
    """Serialise a single Card to vCard text string. Returns '' on failure."""
    try:
        now_iso = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        v = vobject.vCard()

        v.add("version").value = target_version

        fn = c.fn or c.n or "Unnamed"
        v.add("fn").value = fn

        name_obj = _name_to_vobject(c.name)
        if name_obj is not None:
            v.add("n").value = name_obj

        if c.name.prefix and c.fn and not c.fn.startswith(c.name.prefix):
            v.fn.value = f"{c.name.prefix} {c.fn}"

        # Emails — write with TYPE params (HOME/WORK) from typed_emails
        typed_email_map = {tv.value: tv.type for tv in (c.typed_emails or [])}
        for e in sorted(set(c.emails)):
            it = v.add("email")
            it.value = e
            etype = typed_email_map.get(e, "").upper()
            if etype and etype not in ("INTERNET",):
                it.type_param = [etype, "INTERNET"]
            else:
                it.type_param = "INTERNET"

        # Tels — write with TYPE params (HOME/WORK/CELL) from typed_tels
        typed_tel_map = {tv.value: tv.type for tv in (c.typed_tels or [])}
        for t in sorted(set(c.tels)):
            tel = v.add("tel")
            tel.value = t
            ttype = typed_tel_map.get(t, "").upper()
            if ttype:
                tel.type_param = ttype

        if c.org:
            try:
                v.add("org").value = [c.org]
            except Exception:
                pass

        if c.title:
            v.add("title").value = c.title

        if c.bday:
            v.add("bday").value = c.bday

        if c.anniversary and target_version == "4.0":
            v.add("anniversary").value = c.anniversary

        # RELATED (vCard 4.0)
        if target_version == "4.0":
            for rel in (c.related or []):
                try:
                    val = rel.value_str()
                    if not val:
                        continue
                    r = v.add("related")
                    r.value = val
                    if rel.rel_type:
                        r.params["TYPE"] = [rel.rel_type]
                except Exception:
                    pass

        # MEMBER (vCard 4.0, org/group KIND) — UIDs of member contacts
        if target_version == "4.0":
            for uid_ref in (c.member or []):
                if not uid_ref:
                    continue
                try:
                    m = v.add("member")
                    m.value = uid_ref if uid_ref.startswith("urn:uuid:") else f"urn:uuid:{uid_ref}"
                except Exception:
                    pass

        # UID
        if c.uid:
            v.add("uid").value = c.uid

        # KIND (vCard 4.0 only)
        if c.kind and target_version == "4.0":
            v.add("kind").value = c.kind
        # GENDER (vCard 4.0 only)
        if c.gender and target_version == "4.0":
            v.add("gender").value = c.gender

        for a in c.addresses:
            _address_to_vobject(v, a)

        if c.note:
            v.add("note").value = c.note

        if c.categories:
            v.add("categories").value = sorted(set(c.categories))

        # PRODID — identifies vCard Studio
        v.add("prodid").value = PRODID

        # _waived fields — persist as X- property so they survive checkpoint round-trips
        waived = getattr(c, "_waived", None)
        if waived:
            v.add("x-vcard-studio-waived").value = ",".join(sorted(waived))

        # X-IOS-GIVEN / X-IOS-FAMILY — non-destructive iOS display name override
        x_ios_given  = getattr(c, "x_ios_given",  None)
        x_ios_family = getattr(c, "x_ios_family", None)
        if x_ios_given:
            v.add("x-ios-given").value = x_ios_given
        if x_ios_family:
            v.add("x-ios-family").value = x_ios_family

        # REV — card's own revision timestamp if set, else now
        v.add("rev").value = c.rev or now_iso

        return v.serialize()

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Serialisation failed for %r: %s", c.fn or c.org or "Unnamed", exc
        )
        return ""


def card_to_vcf_text(card: Card, target_version: str = "4.0") -> str:
    """Return the vCard text for a single card (used by the raw viewer)."""
    return _serialise_one(card, target_version)


# ---------------------------------------------------------------------------
# Apple / iOS compatibility serialiser (vCard 3.0)
# ---------------------------------------------------------------------------

def _serialise_one_apple(c: Card) -> str:
    """Serialise a single Card to vCard 3.0 format optimised for Apple iOS/iCloud.

    4.0-only fields (KIND, GENDER, RELATED, MEMBER, ANNIVERSARY) are stripped
    from the structured data but preserved verbatim in an appended NOTE block
    so that no information is permanently lost. TEL values are written as plain
    phone numbers (not URI format) for maximum iPhone compatibility.
    Returns '' on failure.
    """
    try:
        now_iso = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        v = vobject.vCard()
        v.add("version").value = "3.0"

        fn = c.fn or "Unnamed"
        v.add("fn").value = fn

        # iOS name override: if X-IOS-GIVEN/FAMILY set, use them for N and FN
        # This is non-destructive — the real name fields are unchanged
        x_ios_given  = getattr(c, "x_ios_given",  None)
        x_ios_family = getattr(c, "x_ios_family", None)
        if x_ios_given or x_ios_family:
            from .model import NameComponents as _NC
            ios_name = _NC(
                given    = x_ios_given  or (c.name.given  if c.name else None),
                family   = x_ios_family or (c.name.family if c.name else None),
                prefix   = c.name.prefix   if c.name else None,
                suffix   = c.name.suffix   if c.name else None,
                additional = c.name.additional if c.name else None,
            )
            ios_name_obj = _name_to_vobject(ios_name)
            if ios_name_obj is not None:
                v.add("n").value = ios_name_obj
            # FN: prefix + ios name if no prefix already in fn
            ios_full = " ".join(p for p in [
                c.name.prefix if c.name else None,
                x_ios_given,
                x_ios_family,
            ] if p)
            if ios_full:
                v.fn.value = ios_full
        else:
            name_obj = _name_to_vobject(c.name)
            if name_obj is not None:
                v.add("n").value = name_obj

            if c.name and c.name.prefix and c.fn and not c.fn.startswith(c.name.prefix):
                v.fn.value = f"{c.name.prefix} {c.fn}"

        # EMAIL
        typed_email_map = {tv.value: tv.type for tv in (c.typed_emails or [])}
        for e in sorted(set(c.emails)):
            it = v.add("email")
            it.value = e
            etype = typed_email_map.get(e, "").upper()
            if etype and etype not in ("INTERNET",):
                it.type_param = [etype, "INTERNET"]
            else:
                it.type_param = "INTERNET"

        # TEL — write plain E.164 numbers, not VALUE=uri:tel: format
        # Strip any accidental tel: prefix that might have crept in
        typed_tel_map = {tv.value: tv.type for tv in (c.typed_tels or [])}
        for t in sorted(set(c.tels)):
            tel = v.add("tel")
            # Ensure we never write 'tel:+44...' — strip any URI prefix
            tel.value = t.removeprefix("tel:").strip()
            ttype = typed_tel_map.get(t, "").upper()
            if ttype:
                tel.type_param = ttype

        if c.org:
            try:
                v.add("org").value = [c.org]
            except Exception:
                pass

        if c.title:
            v.add("title").value = c.title

        if c.bday:
            v.add("bday").value = c.bday

        for a in c.addresses:
            _address_to_vobject(v, a)

        if c.categories:
            v.add("categories").value = sorted(set(c.categories))

        if c.uid:
            v.add("uid").value = c.uid

        # Mark self card as the device owner's "My Card"
        if c.kind == "self":
            v.add("x-abshowas").value = "PROFILE"

        # Build the metadata preservation block for stripped 4.0 fields
        meta_lines: list[str] = []

        if c.kind and c.kind != "individual":
            meta_lines.append(f"KIND: {c.kind}")

        if c.gender:
            meta_lines.append(f"GENDER: {c.gender}")

        if c.anniversary:
            meta_lines.append(f"ANNIVERSARY: {c.anniversary}")

        if c.categories:
            meta_lines.append(f"CATEGORIES: {', '.join(sorted(set(c.categories)))}")

        for rel in (c.related or []):
            val = rel.value_str() if hasattr(rel, "value_str") else str(rel)
            if val:
                rtype = rel.rel_type if hasattr(rel, "rel_type") and rel.rel_type else ""
                meta_lines.append(f"RELATED{('[' + rtype + ']') if rtype else ''}: {val}")

        for uid_ref in (c.member or []):
            if uid_ref:
                meta_lines.append(f"MEMBER: {uid_ref}")

        # Compose NOTE: existing note + appended metadata block (single line, no embedded newlines)
        existing_note = (c.note or "").strip()
        if meta_lines:
            meta_block = "[vCS: " + " | ".join(meta_lines) + "]"
            combined_note = f"{existing_note}  {meta_block}".strip() if existing_note else meta_block
        else:
            combined_note = existing_note

        if combined_note:
            v.add("note").value = combined_note

        v.add("prodid").value = PRODID
        v.add("rev").value = c.rev or now_iso

        # vobject serialises with \r\n — return as-is, no post-processing
        return v.serialize()

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Apple serialisation failed for %r: %s", c.fn or c.org or "Unnamed", exc
        )
        return ""


def export_vcards(cards: list[Card], path: Path, target_version: str = "4.0", apple_compat: bool = False) -> int:
    """Serialise all cards to one combined VCF file."""
    cards_sorted = sorted(cards, key=lambda c: (c.fn or "", c.org or ""))
    lines: list[str] = []
    skipped = 0

    serialise = _serialise_one_apple if apple_compat else lambda c: _serialise_one(c, target_version)

    for c in cards_sorted:
        text = serialise(c)
        if text:
            lines.append(text)
        else:
            skipped += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")

    written = len(cards_sorted) - skipped
    if skipped:
        import logging
        logging.getLogger(__name__).warning(
            "Export: %d written, %d skipped", written, skipped
        )
    return written


def _slug(text: str, max_len: int = 30) -> str:
    """Filesystem-safe ASCII slug."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w-]", "-", ascii_str).strip("-")
    return slug[:max_len]


def export_vcards_individual(
    cards: list[Card],
    out_dir: Path,
    target_version: str = "4.0",
    apple_compat: bool = False,
) -> tuple[int, int]:
    """Export each card as its own .vcf file.

    Filename format:  vcard-<ISO8601>-<LastName>-<FirstName>.vcf
    Returns (written, skipped).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    iso_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    written = 0
    skipped = 0

    serialise = _serialise_one_apple if apple_compat else lambda c: _serialise_one(c, target_version)

    for c in sorted(cards, key=lambda c: (c.name.family or c.fn or "", c.name.given or "")):
        text = serialise(c)
        if not text:
            skipped += 1
            continue

        last  = _slug(c.name.family or "")
        first = _slug(c.name.given  or "")
        if not last and not first:
            last = _slug(c.org or c.fn or "Unnamed")

        parts = ["vcard", iso_ts]
        if last:
            parts.append(last)
        if first:
            parts.append(first)
        base = "-".join(parts)

        target = out_dir / f"{base}.vcf"
        ctr = 1
        while target.exists():
            target = out_dir / f"{base}-{ctr}.vcf"
            ctr += 1

        target.write_text(text, encoding="utf-8")
        written += 1

    return written, skipped
