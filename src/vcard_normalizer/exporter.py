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
                    r = v.add("related")
                    r.value = rel.value_str()
                    r.type_param = rel.rel_type
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
    """Return the vCard 4.0 text for a single card (used by the raw viewer)."""
    return _serialise_one(card, target_version)


def export_vcards(cards: list[Card], path: Path, target_version: str = "4.0") -> int:
    """Serialise all cards to one combined VCF file."""
    cards_sorted = sorted(cards, key=lambda c: (c.fn or "", c.n or ""))
    lines: list[str] = []
    skipped = 0

    for c in cards_sorted:
        text = _serialise_one(c, target_version)
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
) -> tuple[int, int]:
    """Export each card as its own .vcf file.

    Filename format:  vcard-<ISO8601>-<LastName>-<FirstName>.vcf
    Returns (written, skipped).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    iso_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    written = 0
    skipped = 0

    for c in sorted(cards, key=lambda c: (c.name.family or c.fn or "", c.name.given or "")):
        text = _serialise_one(c, target_version)
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
