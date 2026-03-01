"""Standalone similarity scorer — imported by both dedupe and interactive
to avoid a circular import."""
from __future__ import annotations

import re
from rapidfuzz import fuzz
from .model import Card


def _tel_key(t: str) -> str:
    digits = re.sub(r"\D", "", t)
    return digits[-9:] if len(digits) >= 9 else digits


def similarity(a: Card, b: Card) -> float:
    score = 0.0
    if a.uid and b.uid and a.uid == b.uid:
        return 100.0
    if a.emails and b.emails and set(a.emails) & set(b.emails):
        score += 60
    a_tel_keys = {_tel_key(t) for t in a.tels}
    b_tel_keys = {_tel_key(t) for t in b.tels}
    if a_tel_keys and b_tel_keys and a_tel_keys & b_tel_keys:
        score += 40
    if a.fn and b.fn:
        score += 0.4 * fuzz.token_sort_ratio(a.fn, b.fn)
    if a.org and b.org and a.org.lower() == b.org.lower():
        score += 10
    return min(score, 100.0)
