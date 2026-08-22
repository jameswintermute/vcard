from __future__ import annotations

from .interactive import pick_merge
from .model import Card
from .merge import merge_cards_preserving_base
from ._similarity import similarity, _tel_key


def key_email(card: Card) -> str | None:
    return card.emails[0] if card.emails else None


def key_tel(card: Card) -> str | None:
    return card.tels[0] if card.tels else None


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


def _merge_categories(cluster: list[Card]) -> tuple[list[str], bool]:
    """Union categories from all cards in the cluster.

    Returns (merged_categories, had_conflict) where had_conflict is True if
    two cards had *different* non-empty category sets (so the caller can flag
    it for interactive review).
    """
    non_empty = [set(c.categories) for c in cluster if c.categories]
    if not non_empty:
        return [], False
    if len(non_empty) == 1:
        # Only one source had categories — use it, no conflict
        return sorted(non_empty[0]), False
    # Multiple sources both had categories — check if they differ
    union = set()
    for cats in non_empty:
        union |= cats
    conflict = len({frozenset(s) for s in non_empty}) > 1
    return sorted(union), conflict


def merge_cluster_auto(cluster: list[Card]) -> Card:
    """Non-interactive lossless merge, preserving the first card as authority.

    ``find_duplicate_clusters`` preserves input order, so during additive import
    an existing master card appears before newly imported cards.  All useful
    multi-value data is unioned and populated scalar values on the base are not
    overwritten.
    """
    if not cluster:
        raise ValueError("merge_cluster_auto requires at least one card")

    base = cluster[0]
    aliases = [c.fn for c in cluster[1:] if c.fn and c.fn != base.fn]
    for incoming in cluster[1:]:
        merge_cards_preserving_base(base, incoming)

    if len(cluster) > 1:
        base.log_change(
            f"Auto-merged {len(cluster)} duplicate(s) losslessly"
            + (f" (also seen as: {', '.join(aliases)})" if aliases else "")
        )
    return base


def merge_cluster_interactive(cluster: list[Card], idx: int = 0, total: int = 0) -> Card:
    return pick_merge(cluster, idx=idx, total=total)
