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


# ══════════════════════════════════════════════════════════════════════════════
# Reviewed, zero-loss manual merge
#
#   Pass 1  union    — gather every value from every selected card, with provenance
#   Pass 2  dedupe   — collapse by meaning (E.164 phones, case-folded emails,
#                      normalised addresses/URLs), never by raw string
#   Pass 3  review   — MergePlan.to_json() is shown to the user, who picks the
#                      primary card, resolves scalar conflicts, and may untick
#                      list values
#   Pass 4  commit   — MergePlan.apply() builds the survivor and repoints links.
#                      The caller archives the complete original cards first, so
#                      every value the user did not keep still exists on disk.
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

SCALAR_FIELDS: list[tuple[str, str]] = [
    ("name.prefix", "prefix"),
    ("name.given", "first name"),
    ("name.additional", "middle name"),
    ("name.family", "last name"),
    ("name.suffix", "suffix"),
    ("fn", "display name"),
    ("org", "org"),
    ("title", "job title"),
    ("bday", "birthday"),
    ("anniversary", "anniversary"),
    ("kind", "kind"),
    ("gender", "gender"),
    ("x_ios_given", "iOS first name"),
    ("x_ios_family", "iOS last name"),
]

LIST_FIELDS = ("emails", "tels", "urls", "addresses", "nicknames", "categories", "related", "member")


def _get_field(card: Card, path: str):
    if path.startswith("name."):
        return getattr(card.name, path[5:], "") or ""
    return getattr(card, path, None) or ""


def _set_field(card: Card, path: str, value: str) -> None:
    if path.startswith("name."):
        setattr(card.name, path[5:], value or "")
    else:
        setattr(card, path, value or None)


def _tel_key(value: str, region: str) -> str:
    raw = (value or "").strip()
    try:
        import phonenumbers
        parsed = phonenumbers.parse(raw, region)
        # A comparison key only — the stored value is never rewritten here, so
        # "possible" (right length for the region) is enough to compare numbers.
        if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    digits = _re.sub(r"\D", "", raw)
    return ("+" if raw.startswith("+") else "") + digits


def _url_key(value: str) -> str:
    v = (value or "").strip().casefold()
    v = _re.sub(r"^https?://", "", v)
    v = _re.sub(r"^www\.", "", v)
    return v.rstrip("/")


def _addr_key(a: Address) -> str:
    def n(v):
        return _re.sub(r"[\s,.]+", " ", (v or "").casefold()).strip()
    postcode = _re.sub(r"\s+", "", (a.postal_code or "").casefold())
    return "|".join([n(a.po_box), n(a.extended), n(a.street), n(a.locality),
                     n(a.region), postcode, n(a.country)])


def _addr_display(a: Address) -> str:
    return ", ".join(p for p in (a.po_box, a.extended, a.street, a.locality,
                                 a.region, a.postal_code, a.country) if p)


class _Item:
    """One deduplicated list value plus every source object that produced it."""

    def __init__(self, key: str):
        self.key = key
        self.objs: list[tuple[str, object]] = []   # (source uid, original object)

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(uid for uid, _ in self.objs))

    def types(self) -> list[str]:
        out = []
        for _, o in self.objs:
            t = (getattr(o, "type", "") or "").upper()
            if t and t not in out:
                out.append(t)
        return out


class MergePlan:
    def __init__(self, cards: list[Card], *, region: str = "GB", primary_uid: str | None = None):
        if len(cards) < 2:
            raise ValueError("A merge needs at least two cards")
        if any(not c.uid for c in cards):
            raise ValueError("Every card in a merge must have a UID")
        if len({c.uid for c in cards}) != len(cards):
            raise ValueError("Duplicate card in merge selection")
        self.cards = cards
        self.region = region
        by_uid = {c.uid: c for c in cards}
        if primary_uid and primary_uid in by_uid:
            self.primary = by_uid[primary_uid]
        else:
            self.primary = max(cards, key=card_richness)
        # Primary first so its values/formatting are the defaults.
        self.ordered = [self.primary] + [c for c in cards if c is not self.primary]
        self.cluster_uids: set[str] = set()
        for c in cards:
            self.cluster_uids.add(c.uid)
            self.cluster_uids.update(c.external_uids or [])
        self._build()

    # ── Pass 1 + 2 ───────────────────────────────────────────────────────────
    def _add(self, bucket: dict, key: str, uid: str, obj) -> None:
        if not key:
            return
        item = bucket.get(key)
        if item is None:
            item = bucket[key] = _Item(key)
        item.objs.append((uid, obj))

    def _build(self) -> None:
        self.scalars: dict[str, list[tuple[str, list[str]]]] = {}
        for path, _ in SCALAR_FIELDS:
            cands: dict[str, tuple[str, list[str]]] = {}
            for c in self.ordered:
                v = str(_get_field(c, path)).strip()
                if not v:
                    continue
                k = _norm(v)
                if k in cands:
                    cands[k][1].append(c.uid)
                else:
                    cands[k] = (v, [c.uid])
            self.scalars[path] = list(cands.values())

        self.lists: dict[str, dict[str, _Item]] = {f: {} for f in LIST_FIELDS}
        for c in self.ordered:
            u = c.uid
            typed_e = {_norm(tv.value): tv for tv in c.typed_emails or []}
            for e in c.emails or []:
                self._add(self.lists["emails"], _norm(e), u, typed_e.get(_norm(e), TypedValue(value=e)))
            typed_t = {_norm(tv.value): tv for tv in c.typed_tels or []}
            for t in c.tels or []:
                self._add(self.lists["tels"], _tel_key(t, self.region), u,
                          typed_t.get(_norm(t), TypedValue(value=t)))
            for tv in c.urls or []:
                self._add(self.lists["urls"], _url_key(tv.value), u, tv)
            for a in c.addresses or []:
                self._add(self.lists["addresses"], _addr_key(a), u, a)
            for n in c.nicknames or []:
                self._add(self.lists["nicknames"], _norm(n), u, n)
            for cat in c.categories or []:
                self._add(self.lists["categories"], _norm(cat), u, cat)
            for r in c.related or []:
                if r.uid and r.uid in self.cluster_uids:
                    continue          # link between cards being merged → would be a self-link
                key = f"{_norm(r.rel_type)}|uid:{r.uid}" if r.uid else f"{_norm(r.rel_type)}|text:{_norm(r.text)}"
                self._add(self.lists["related"], key, u, r)
            for m in c.member or []:
                mm = m[9:] if m.startswith("urn:uuid:") else m
                if mm in self.cluster_uids:
                    continue
                self._add(self.lists["member"], mm, u, mm)

        notes: dict[str, tuple[str, list[str]]] = {}
        for c in self.ordered:
            v = (c.note or "").strip()
            if v:
                k = _norm(v)
                if k in notes:
                    notes[k][1].append(c.uid)
                else:
                    notes[k] = (v, [c.uid])
        self.notes = list(notes.values())

    # ── Pass 3: what the reviewer sees ──────────────────────────────────────
    def default_scalar(self, path: str) -> str:
        cands = self.scalars.get(path) or []
        return cands[0][0] if cands else ""

    def default_note(self) -> str:
        return "\n\n".join(v for v, _ in self.notes)

    @staticmethod
    def _display(field: str, item: _Item) -> str:
        o = item.objs[0][1]
        if field == "addresses":
            return _addr_display(o)
        if field == "related":
            return f"{o.rel_type}: {o.text or o.uid}"
        if isinstance(o, str):
            return o
        return getattr(o, "value", str(o))

    def to_json(self) -> dict:
        return {
            "primary": self.primary.uid,
            "cards": [
                {"uid": c.uid, "fn": c.fn or c.org or "(unnamed)",
                 "richness": card_richness(c), "sources": list(c._source_files or [])}
                for c in self.cards
            ],
            "scalars": [
                {"field": path, "label": label,
                 "candidates": [{"value": v, "sources": s} for v, s in self.scalars[path]],
                 "default": self.default_scalar(path),
                 "conflict": len(self.scalars[path]) > 1}
                for path, label in SCALAR_FIELDS if self.scalars[path]
            ],
            "lists": {
                f: [{"key": it.key, "display": self._display(f, it), "sources": it.sources,
                     "types": it.types(), "merged_from": len(it.objs)}
                    for it in self.lists[f].values()]
                for f in LIST_FIELDS
            },
            "notes": [{"value": v, "sources": s} for v, s in self.notes],
            "default_note": self.default_note(),
        }

    # ── Pass 4: build the survivor ──────────────────────────────────────────
    def apply(self, choices: dict | None = None) -> tuple[Card, list[str]]:
        """Mutate the primary card into the merged survivor.

        choices = {
          "scalars": {field: value},          # missing field → default
          "include": {list_field: [keys]},    # missing list → everything
          "types":   {list_field: {key: TYPE}},
          "note":    str | None,              # None → all notes concatenated
        }
        Returns (survivor, absorbed_uids).
        """
        choices = choices or {}
        sc = choices.get("scalars") or {}
        inc = choices.get("include") or {}
        typ = choices.get("types") or {}
        s = self.primary

        for path, _ in SCALAR_FIELDS:
            value = sc[path] if path in sc else self.default_scalar(path)
            _set_field(s, path, (value or "").strip())

        def keep(field: str) -> list[_Item]:
            items = list(self.lists[field].values())
            if field in inc:
                wanted = set(inc[field])
                items = [it for it in items if it.key in wanted]
            return items

        def typed(field: str, it: _Item) -> TypedValue:
            first = it.objs[0][1]
            chosen = (typ.get(field) or {}).get(it.key)
            t = chosen if chosen is not None else (it.types()[0] if it.types() else "")
            label = next((o.label for _, o in it.objs if getattr(o, "label", "")), "")
            pref = any(getattr(o, "pref", False) for _, o in it.objs)
            return TypedValue(value=first.value, type=t, label=label, pref=pref)

        s.typed_emails = [typed("emails", it) for it in keep("emails")]
        s.emails = [tv.value for tv in s.typed_emails]
        s.typed_tels = [typed("tels", it) for it in keep("tels")]
        s.tels = [tv.value for tv in s.typed_tels]
        s.urls = [typed("urls", it) for it in keep("urls")]

        addrs = []
        for it in keep("addresses"):
            a0 = it.objs[0][1]
            clone = Address(**{f.name: getattr(a0, f.name) for f in fields(Address)})
            chosen = (typ.get("addresses") or {}).get(it.key)
            if chosen is not None:
                clone.type = chosen
            else:
                for _, a in it.objs:
                    for attr in ("type", "label", "apple_country_code"):
                        if not getattr(clone, attr) and getattr(a, attr):
                            setattr(clone, attr, getattr(a, attr))
            clone.pref = any(a.pref for _, a in it.objs)
            addrs.append(clone)
        s.addresses = addrs

        s.nicknames = [it.objs[0][1] for it in keep("nicknames")]
        s.categories = sorted({it.objs[0][1] for it in keep("categories")}, key=str.casefold)
        s.related = [Related(rel_type=it.objs[0][1].rel_type, uid=it.objs[0][1].uid,
                             text=it.objs[0][1].text) for it in keep("related")]
        s.member = [it.objs[0][1] for it in keep("member")]

        note = choices.get("note")
        s.note = (self.default_note() if note is None else note).strip() or None

        absorbed = [c for c in self.cards if c is not s]
        absorbed_uids: list[str] = []
        for c in absorbed:
            absorbed_uids.append(c.uid)
            for alias in [c.uid, *(c.external_uids or [])]:
                if alias and alias != s.uid and alias not in s.external_uids:
                    s.external_uids.append(alias)
            s._source_files, _ = _union_strings(s._source_files, c._source_files, casefold=False)
            s._waived = set(s._waived or set()) | set(c._waived or set())
            for key, value in (c.props or {}).items():
                s.props.setdefault(key, value)

        s.rev = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        s.log_change(f"Reviewed merge of {len(self.cards)} cards; originals archived")
        return s, absorbed_uids


def repoint_links(all_cards: list[Card], survivor: Card, old_uids: set[str]) -> int:
    """Point RELATED/MEMBER references at *old_uids* to the survivor. Returns count."""
    changed = 0
    for c in all_cards:
        if c is survivor:
            continue
        new_rel, seen = [], set()
        for r in c.related or []:
            if r.uid and r.uid in old_uids:
                r = Related(rel_type=r.rel_type, uid=survivor.uid, text=r.text)
                changed += 1
            key = (_norm(r.rel_type), r.uid or "", _norm(r.text) if not r.uid else "")
            if key not in seen:
                seen.add(key)
                new_rel.append(r)
        c.related = new_rel
        new_mem = []
        for m in c.member or []:
            bare = m[9:] if m.startswith("urn:uuid:") else m
            if bare in old_uids:
                bare, m = survivor.uid, survivor.uid
                changed += 1
            if m not in new_mem:
                new_mem.append(m)
        c.member = new_mem
    return changed
