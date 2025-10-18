from __future__ import annotations
from typing import List, Dict, Tuple
from rapidfuzz import fuzz
from .model import Card
from .interactive import pick_merge

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
    if a.tels and b.tels and set(a.tels) & set(b.tels):
        score += 40
    if a.fn and b.fn:
        score += 0.4 * fuzz.token_sort_ratio(a.fn, b.fn)
    if a.org and b.org and a.org == b.org:
        score += 10
    return min(score, 100.0)

def find_duplicate_clusters(cards: List[Card]) -> List[List[Card]]:
    # naive O(n^2) clustering for milestone 1; optimize later
    visited = set()
    clusters: List[List[Card]] = []
    for i, c in enumerate(cards):
        if i in visited:
            continue
        cluster = [c]
        visited.add(i)
        for j in range(i+1, len(cards)):
            if j in visited: 
                continue
            if similarity(c, cards[j]) >= 70:
                cluster.append(cards[j])
                visited.add(j)
        clusters.append(cluster)
    return clusters

def merge_cluster_auto(cluster: List[Card]) -> Card:
    # prefer the card with most info; union of emails/tels
    best = max(cluster, key=lambda c: (len(c.emails)+len(c.tels), len((c.fn or ""))))
    emails = sorted({e for c in cluster for e in c.emails})
    tels = sorted({t for c in cluster for t in c.tels})
    best.emails = emails
    best.tels = tels
    return best

def merge_cluster_interactive(cluster: List[Card]) -> Card:
    return pick_merge(cluster)
