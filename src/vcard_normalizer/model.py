from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Card:
    # Minimal internal normalized model; we also keep raw vobject for fidelity.
    raw: Any
    fn: str | None = None
    n: str | None = None
    emails: List[str] = field(default_factory=list)
    tels: List[str] = field(default_factory=list)
    org: str | None = None
    title: str | None = None
    bday: str | None = None
    uid: str | None = None
    rev: str | None = None
    props: Dict[str, Any] = field(default_factory=dict)  # remaining props
