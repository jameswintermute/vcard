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
class Card:
    raw: Any
    fn: str | None = None
    n: str | None = None
    emails: list[str] = field(default_factory=list)
    tels: list[str] = field(default_factory=list)
    org: str | None = None
    title: str | None = None
    bday: str | None = None
    uid: str | None = None
    rev: str | None = None
    addresses: list[Address] = field(default_factory=list)
    kind: str | None = None           # vCard 4.0 KIND: individual|org
    categories: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)  # remaining props
