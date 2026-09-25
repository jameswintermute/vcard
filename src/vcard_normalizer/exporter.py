from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import vobject

from .model import Address, Card, NameComponents

PRODID = "-//vCard Studio//https://github.com/jameswintermute/vcard//EN"


def _apply_common_params(prop, *, type_value: str = "", label: str = "", pref: bool = False, version: str = "4.0", email: bool = False) -> None:
    types: list[str] = []
    if type_value:
        types.append(type_value.upper())
    if email and "INTERNET" not in types:
        types.append("INTERNET")
    if version == "3.0" and pref:
        types.append("PREF")
    if types:
        prop.params["TYPE"] = list(dict.fromkeys(types))
    if version == "4.0" and pref:
        prop.params["PREF"] = ["1"]
    if label:
        # Canonical vCard has no general custom-label property. Persist it as a
        # parameter owned by vCard Studio so a master save/load is lossless.
        prop.params["X-VCARD-STUDIO-LABEL"] = [label]


def _address_to_vobject(
    v: vobject.vCard,
    a: Address,
    *,
    target_version: str = "4.0",
    persist_metadata: bool = True,
):
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
        _apply_common_params(
            adr,
            type_value=a.type,
            label=a.label if persist_metadata else "",
            pref=a.pref,
            version=target_version,
        )
        if persist_metadata and a.apple_country_code:
            adr.params["X-VCARD-STUDIO-APPLE-ADR"] = [a.apple_country_code]
        return adr
    except Exception:
        return None


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


def _typed_lookup(values) -> dict[str, object]:
    return {tv.value: tv for tv in (values or []) if getattr(tv, "value", None)}


def _serialise_one(c: Card, target_version: str = "4.0") -> str:
    """Serialise a canonical vCard, preserving vCard Studio-only metadata."""
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

        email_meta = _typed_lookup(c.typed_emails)
        for email in sorted(set(c.emails)):
            prop = v.add("email")
            prop.value = email
            meta = email_meta.get(email)
            _apply_common_params(
                prop,
                type_value=getattr(meta, "type", ""),
                label=getattr(meta, "label", ""),
                pref=bool(getattr(meta, "pref", False)),
                version=target_version,
                email=True,
            )

        tel_meta = _typed_lookup(c.typed_tels)
        for tel_value in sorted(set(c.tels)):
            prop = v.add("tel")
            prop.value = tel_value
            meta = tel_meta.get(tel_value)
            _apply_common_params(
                prop,
                type_value=getattr(meta, "type", ""),
                label=getattr(meta, "label", ""),
                pref=bool(getattr(meta, "pref", False)),
                version=target_version,
            )

        for url_meta in c.urls or []:
            if not url_meta.value:
                continue
            prop = v.add("url")
            prop.value = url_meta.value
            _apply_common_params(
                prop,
                type_value=url_meta.type,
                label=url_meta.label,
                pref=url_meta.pref,
                version=target_version,
            )

        if c.nicknames:
            v.add("nickname").value = ",".join(dict.fromkeys(c.nicknames))

        if c.org:
            v.add("org").value = [c.org]
        if c.title:
            v.add("title").value = c.title
        if c.bday:
            v.add("bday").value = c.bday
        if c.anniversary and target_version == "4.0":
            v.add("anniversary").value = c.anniversary

        if target_version == "4.0":
            for rel in c.related or []:
                value = rel.value_str()
                if not value:
                    continue
                prop = v.add("related")
                prop.value = value
                if rel.rel_type:
                    prop.params["TYPE"] = [rel.rel_type]

        # MEMBER is standards-valid only for KIND=group.  Existing organisation
        # membership is preserved in an X-property rather than emitted invalidly.
        if target_version == "4.0" and c.kind == "group":
            for uid_ref in c.member or []:
                prop = v.add("member")
                prop.value = uid_ref if uid_ref.startswith("urn:uuid:") else f"urn:uuid:{uid_ref}"
        elif c.member:
            for uid_ref in c.member:
                v.add("x-vcard-studio-member").value = uid_ref

        if c.uid:
            v.add("uid").value = c.uid
        for external_uid in dict.fromkeys(c.external_uids or []):
            if external_uid and external_uid != c.uid:
                v.add("x-vcard-studio-external-uid").value = external_uid

        if target_version == "4.0" and c.kind:
            if c.kind == "self":
                v.add("kind").value = "individual"
                v.add("x-vcard-studio-kind").value = "self"
            else:
                v.add("kind").value = c.kind
        if c.gender and target_version == "4.0":
            v.add("gender").value = c.gender

        for address in c.addresses:
            _address_to_vobject(v, address, target_version=target_version)

        if c.note:
            v.add("note").value = c.note
        if c.categories:
            v.add("categories").value = sorted(set(c.categories))

        v.add("prodid").value = PRODID
        if c._waived:
            v.add("x-vcard-studio-waived").value = ",".join(sorted(c._waived))
        if c.x_ios_given:
            v.add("x-ios-given").value = c.x_ios_given
        if c.x_ios_family:
            v.add("x-ios-family").value = c.x_ios_family
        v.add("rev").value = c.rev or now_iso
        return v.serialize()

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Serialisation failed for %r: %s", c.fn or c.org or "Unnamed", exc
        )
        return ""


def card_to_vcf_text(card: Card, target_version: str = "4.0") -> str:
    """Return the canonical vCard text for a single card."""
    return _serialise_one(card, target_version)


# ---------------------------------------------------------------------------
# Apple / iOS compatibility serialiser (vCard 3.0)
# ---------------------------------------------------------------------------

def _apple_wire_label(label: str) -> str:
    label = (label or "").strip()
    system = {
        "home": "Home",
        "work": "Work",
        "mobile": "Mobile",
        "main": "Main",
        "other": "Other",
        "anniversary": "Anniversary",
        "spouse": "Spouse",
        "partner": "Partner",
        "parent": "Parent",
        "child": "Child",
        "sibling": "Sibling",
        "friend": "Friend",
    }
    if label.casefold() in system:
        return f"_$!<{system[label.casefold()]}>!$_"
    return label


def _apple_group(v: vobject.vCard, prop, counter: list[int], *, label: str = "", adr_code: str = "") -> None:
    if not label and not adr_code:
        return
    group = f"item{counter[0]}"
    counter[0] += 1
    # vobject ContentLine exposes the vCard group prefix through .group.
    prop.group = group
    if label:
        meta = v.add("x-ablabel")
        meta.group = group
        meta.value = _apple_wire_label(label)
    if adr_code:
        meta = v.add("x-abadr")
        meta.group = group
        meta.value = adr_code


def _serialise_one_apple(c: Card) -> str:
    """Serialise vCard 3.0 optimised for Apple Contacts/iCloud.

    Apple-native grouped labels/company/profile/special-date hints are emitted
    where possible. Central-only fields are additionally retained in the vCS
    NOTE capsule, making a vCard Studio → Apple → vCard Studio round trip
    non-destructive even when Apple cannot represent a field directly.
    """
    try:
        now_iso = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        v = vobject.vCard()
        v.add("version").value = "3.0"
        group_counter = [1]

        v.add("fn").value = c.fn or "Unnamed"
        if c.x_ios_given or c.x_ios_family:
            from .model import NameComponents as _NC
            ios_name = _NC(
                given=c.x_ios_given or c.name.given,
                family=c.x_ios_family or c.name.family,
                prefix=c.name.prefix,
                suffix=c.name.suffix,
                additional=c.name.additional,
            )
            name_obj = _name_to_vobject(ios_name)
            if name_obj is not None:
                v.add("n").value = name_obj
            ios_full = " ".join(p for p in [c.name.prefix, c.x_ios_given, c.x_ios_family] if p)
            if ios_full:
                v.fn.value = ios_full
        else:
            name_obj = _name_to_vobject(c.name)
            if name_obj is not None:
                v.add("n").value = name_obj
            if c.name.prefix and c.fn and not c.fn.startswith(c.name.prefix):
                v.fn.value = f"{c.name.prefix} {c.fn}"

        email_meta = _typed_lookup(c.typed_emails)
        for email in sorted(set(c.emails)):
            prop = v.add("email")
            prop.value = email
            meta = email_meta.get(email)
            _apply_common_params(
                prop,
                type_value=getattr(meta, "type", ""),
                pref=bool(getattr(meta, "pref", False)),
                version="3.0",
                email=True,
            )
            _apple_group(v, prop, group_counter, label=getattr(meta, "label", ""))

        tel_meta = _typed_lookup(c.typed_tels)
        for tel_value in sorted(set(c.tels)):
            prop = v.add("tel")
            prop.value = tel_value.removeprefix("tel:").strip()
            meta = tel_meta.get(tel_value)
            _apply_common_params(
                prop,
                type_value=getattr(meta, "type", ""),
                pref=bool(getattr(meta, "pref", False)),
                version="3.0",
            )
            _apple_group(v, prop, group_counter, label=getattr(meta, "label", ""))

        for url_meta in c.urls or []:
            if not url_meta.value:
                continue
            prop = v.add("url")
            prop.value = url_meta.value
            _apply_common_params(
                prop,
                type_value=url_meta.type,
                pref=url_meta.pref,
                version="3.0",
            )
            _apple_group(v, prop, group_counter, label=url_meta.label)

        if c.nicknames:
            v.add("nickname").value = ",".join(dict.fromkeys(c.nicknames))
        if c.org:
            v.add("org").value = [c.org]
        if c.title:
            v.add("title").value = c.title
        if c.bday:
            v.add("bday").value = c.bday

        for address in c.addresses:
            prop = _address_to_vobject(v, address, target_version="3.0", persist_metadata=False)
            if prop is not None:
                _apple_group(
                    v,
                    prop,
                    group_counter,
                    label=address.label,
                    adr_code=address.apple_country_code,
                )

        if c.categories:
            v.add("categories").value = sorted(set(c.categories))
        if c.uid:
            v.add("uid").value = c.uid

        if c.kind == "self":
            v.add("x-abshowas").value = "PROFILE"
        elif c.kind == "org":
            v.add("x-abshowas").value = "COMPANY"

        # Native Apple anniversary/special-date hint.
        if c.anniversary:
            date_prop = v.add("x-abdate")
            date_prop.value = c.anniversary
            _apple_group(v, date_prop, group_counter, label="Anniversary")

        # Native Apple related-name hints for relationships that have text.
        for rel in c.related or []:
            if rel.text:
                rel_prop = v.add("x-abrelatednames")
                rel_prop.value = rel.text
                _apple_group(v, rel_prop, group_counter, label=rel.rel_type or "Related")

        meta_lines: list[str] = []
        if c.kind and c.kind != "individual":
            meta_lines.append(f"KIND: {c.kind}")
        if c.gender:
            meta_lines.append(f"GENDER: {c.gender}")
        if c.anniversary:
            meta_lines.append(f"ANNIVERSARY: {c.anniversary}")
        if c.categories:
            meta_lines.append(f"CATEGORIES: {', '.join(sorted(set(c.categories)))}")
        for rel in c.related or []:
            value = rel.value_str()
            if value:
                meta_lines.append(f"RELATED[{rel.rel_type or 'contact'}]: {value}")
        for uid_ref in c.member or []:
            if uid_ref:
                meta_lines.append(f"MEMBER: {uid_ref}")

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
