from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TypedValue:
    """A string value with optional vCard/Apple type metadata."""

    value: str
    type: str = ""   # HOME | WORK | CELL | FAX | PAGER | OTHER | custom
    label: str = ""  # Apple/custom display label, e.g. iPhone or Parents
    pref: bool = False

    def label_text(self) -> str:
        """Human-readable label, preferring a custom label over TYPE."""
        return self.label or (self.type.upper() if self.type else "")

    # Backward-compatible helper used by older UI code.
    def display_label(self) -> str:
        return self.label_text()


@dataclass
class Address:
    po_box: str | None = None
    extended: str | None = None
    street: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None  # display country name (not ISO code)
    type: str = ""              # HOME | WORK | OTHER | custom
    label: str = ""             # Apple/custom display label
    pref: bool = False
    apple_country_code: str = ""  # X-ABADR value when supplied by Apple


@dataclass
class NameComponents:
    """Structured N field: family;given;additional;prefix;suffix.

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
        """Human-readable form: prefix given additional family suffix."""
        parts = [p for p in [self.prefix, self.given, self.additional, self.family, self.suffix] if p]
        return " ".join(parts)


@dataclass
class Related:
    """vCard 4.0 RELATED property — link to another contact."""

    rel_type: str = "spouse"   # spouse | partner | friend | sibling | parent | child | kin …
    uid: str | None = None      # local contact UID when linked
    text: str | None = None     # plain-text fallback when no linked UID exists

    def value_str(self) -> str:
        if self.uid:
            return f"urn:uuid:{self.uid}"
        return self.text or ""


@dataclass
class Card:
    raw: Any
    fn: str | None = None
    name: NameComponents = field(default_factory=NameComponents)
    emails: list[str] = field(default_factory=list)
    tels: list[str] = field(default_factory=list)
    typed_emails: list[TypedValue] = field(default_factory=list)
    typed_tels: list[TypedValue] = field(default_factory=list)
    urls: list[TypedValue] = field(default_factory=list)
    nicknames: list[str] = field(default_factory=list)
    org: str | None = None
    title: str | None = None
    bday: str | None = None
    anniversary: str | None = None
    uid: str | None = None
    # Provider/vendor UIDs seen for this logical contact.  The canonical uid above
    # remains owned by vCard Studio; these aliases are used for safe re-import matching.
    external_uids: list[str] = field(default_factory=list)
    rev: str | None = None
    addresses: list[Address] = field(default_factory=list)
    kind: str | None = None        # individual | org | group | location | self (internal)
    gender: str | None = None      # M | F | O | N | U
    categories: list[str] = field(default_factory=list)
    related: list[Related] = field(default_factory=list)
    # RFC 6350 MEMBER is valid for KIND=group. For legacy organisation membership,
    # the exporter persists the values in a vCard Studio X-property instead.
    member: list[str] = field(default_factory=list)
    note: str | None = None
    props: dict[str, Any] = field(default_factory=dict)

    # Non-destructive Apple/iOS display-name overrides used by the UI/exporter.
    x_ios_given: str | None = None
    x_ios_family: str | None = None

    # ── Audit / reporting ─────────────────────────────────────────────────────
    _changes: list[str] = field(default_factory=list, repr=False)
    _source_files: list[str] = field(default_factory=list, repr=False)
    _waived: set = field(default_factory=set, repr=False)

    def log_change(self, msg: str) -> None:
        self._changes.append(msg)

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
