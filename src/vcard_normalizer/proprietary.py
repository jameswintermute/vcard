from __future__ import annotations
import re
from typing import Iterable
from .model import Card

def fold_unfold(text: str) -> str:
    # Placeholder for explicit folding if we need it; vobject handles this on write.
    return text

APPLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^X-AB.*", re.I),
    re.compile(r"^X-ADDRESSBOOKSERVER.*", re.I),
    re.compile(r"^item\d+\..*", re.I),  # legacy iOS group-style
]
GOOGLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^X-GOOGLE.*", re.I),
]
GENERIC_X_PATTERN = re.compile(r"^X-.*", re.I)

WHITELIST = {
    # Example: keep helpful X- properties by default (empty for now)
}

class DefaultStripper:
    def __init__(self, keep_unknown: bool = False):
        self.keep_unknown = keep_unknown

    def _should_strip(self, name: str) -> bool:
        if name.upper() in WHITELIST:
            return False
        if APPLE_PATTERNS and any(p.match(name) for p in APPLE_PATTERNS):
            return True
        if GOOGLE_PATTERNS and any(p.match(name) for p in GOOGLE_PATTERNS):
            return True
        if GENERIC_X_PATTERN.match(name):
            return not self.keep_unknown
        return False

    def strip(self, card: Card) -> Card:
        vc = card.raw
        to_remove = []
        for child in list(vc.getChildren()):
            name = child.name if hasattr(child, "name") else ""
            if self._should_strip(name):
                to_remove.append(child)
        for c in to_remove:
            vc.remove(c)
        return card
