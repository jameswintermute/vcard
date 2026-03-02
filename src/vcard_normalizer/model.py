from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Address:
    po_box: str | None = None
    extended: str | None = None
    street: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None  # display country name (not ISO code)


@dataclass
class NameComponents:
    """Structured N field: family;given;additional;prefix;suffix

    In vCard 4.0 the N property has exactly these five components.
    prefix = honorific prefix  (Mr, Mrs, Dr …)
    suffix = honorific suffix  (Jr, OBE, PhD …)
    """
    family: str = ""
    given: str = ""
    additional: str = ""   # middle name(s)
    prefix: str = ""       # Mr / Mrs / Dr / Rev …
    suffix: str = ""       # Jr / OBE / PhD …

    def to_vcard_str(self) -> str:
        return f"{self.family};{self.given};{self.additional};{self.prefix};{self.suffix}"

    @classmethod
    def from_vcard_str(cls, raw: str) -> "NameComponents":
        parts = raw.split(";")
        while len(parts) < 5:
            parts.append("")
        return cls(
            family=parts[0].strip(),
            given=parts[1].strip(),
            additional=parts[2].strip(),
            prefix=parts[3].strip(),
            suffix=parts[4].strip(),
        )

    def display(self) -> str:
        """Human-readable form: prefix given additional family suffix"""
        parts = [p for p in [self.prefix, self.given, self.additional, self.family, self.suffix] if p]
        return " ".join(parts)


@dataclass
class Related:
    """vCard 4.0 RELATED property — link to another contact."""
    # type is one of the RFC 6350 relation types
    rel_type: str = "spouse"   # spouse | partner | friend | sibling | parent | child | kin | emergency …
    # uid is a urn:uuid: reference if the contact exists in this collection
    uid: str | None = None
    # text is a plain-text fallback (name) when no UID is available
    text: str | None = None

    def value_str(self) -> str:
        if self.uid:
            return f"urn:uuid:{self.uid}"
        return self.text or ""


@dataclass
class Card:
    raw: Any
    fn: str | None = None
    # Structured name — replaces flat n string
    name: NameComponents = field(default_factory=NameComponents)
    # Keep n as a read-only alias for backward compat with old code
    emails: list[str] = field(default_factory=list)
    tels: list[str] = field(default_factory=list)
    org: str | None = None
    title: str | None = None       # job title (TITLE field)
    bday: str | None = None        # BDAY — ISO date or --MMDD
    anniversary: str | None = None # ANNIVERSARY — vCard 4.0
    uid: str | None = None
    rev: str | None = None
    addresses: list[Address] = field(default_factory=list)
    kind: str | None = None        # vCard 4.0 KIND: individual|org|group|location
    categories: list[str] = field(default_factory=list)
    related: list[Related] = field(default_factory=list)  # RELATED — vCard 4.0
    member: list[str] = field(default_factory=list)         # MEMBER — vCard 4.0 (org cards: list of UID URNs)
    note: str | None = None                                 # NOTE field (free text)
    props: dict[str, Any] = field(default_factory=dict)   # remaining props

    # ── Audit / reporting ─────────────────────────────────────────────────────
    _changes: list[str] = field(default_factory=list, repr=False)
    _source_files: list[str] = field(default_factory=list, repr=False)
    # Fields the user has explicitly marked as "not required" (excluded from quality scan)
    # Values: 'email', 'phone', 'address', 'category', 'org'
    _waived: set = field(default_factory=set, repr=False)

    def log_change(self, msg: str) -> None:
        self._changes.append(msg)

    # backward-compat shim — old code that reads card.n gets a serialised string
    @property
    def n(self) -> str | None:
        s = self.name.to_vcard_str()
        return s if s != ";;;;" else None

    @n.setter
    def n(self, value: str | None) -> None:
        if value:
            self.name = NameComponents.from_vcard_str(value)
        else:
            self.name = NameComponents()
