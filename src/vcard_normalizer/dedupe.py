from __future__ import annotations

import re

from rapidfuzz import fuzz

from .interactive import pick_merge
from .model import Card

# ── Phone canonicalisation for dedup purposes only ────────────────────────────
# Strip all non-digit characters, then compare last 9 digits.
# This means +447980220220 and 07980220220 hash to the same key.

def _tel_key(t: str) -> str:
    digits = re.sub(r"\D", "", t)
    return digits[-9:] if len(digits) >= 9 else digits


def key_email(card: Card) -> str | None:
    return card.emails[0] if card.emails else None


def key_tel(card: Card) -> str | None:
    return card.tels[0] if card.tels else None


def similarity(a: Card, b: Card) -> float:
    score = 0.0

    if a.uid and b.uid and a.uid == b.uid:
        return 100.0

    if a.emails and b.emails and set(a.emails) & set(b.emails):
        score += 60

    # Phone comparison using canonicalised keys
    a_tel_keys = {_tel_key(t) for t in a.tels}
    b_tel_keys = {_tel_key(t) for t in b.tels}
    if a_tel_keys and b_tel_keys and a_tel_keys & b_tel_keys:
        score += 40

    if a.fn and b.fn:
        score += 0.4 * fuzz.token_sort_ratio(a.fn, b.fn)

    if a.org and b.org and a.org.lower() == b.org.lower():
        score += 10

    return min(score, 100.0)


def find_duplicate_clusters(cards: list[Card]) -> list[list[Card]]:
    """O(n²) clustering; fast enough for typical address books (<5 000 contacts)."""
    visited: set[int] = set()
    clusters: list[list[Card]] = []
    for i, c in enumerate(cards):
        if i in visited:
            continue
        cluster = [c]
        visited.add(i)
        for j in range(i + 1, len(cards)):
            if j in visited:
                continue
            if similarity(c, cards[j]) >= 70:
                cluster.append(cards[j])
                visited.add(j)
        clusters.append(cluster)
    return clusters


def merge_cluster_auto(cluster: list[Card]) -> Card:
    """Non-interactive merge: take the richest card, union all emails/tels."""
    best = max(cluster, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
    emails = sorted({e for c in cluster for e in c.emails})
    tels = sorted({t for c in cluster for t in c.tels})
    merged_names = [c.fn for c in cluster if c.fn and c.fn != best.fn]
    best.emails = emails
    best.tels = tels
    if len(cluster) > 1:
        best.log_change(
            f"Auto-merged {len(cluster)} duplicate(s)"
            + (f" (also seen as: {', '.join(merged_names)})" if merged_names else "")
        )
    return best


def merge_cluster_interactive(cluster: list[Card]) -> Card:
    return pick_merge(cluster)

