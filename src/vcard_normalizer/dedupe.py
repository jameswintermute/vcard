from __future__ import annotations

from .interactive import pick_merge
from .model import Card
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
    """Non-interactive merge: take the richest card, union all fields.

    Categories are unioned from all sources. If only one source had
    categories those are taken as-is. Conflicts (different non-empty sets)
    are noted in the change log but the union is still used — the
    post-processing review prompt can surface these to the user.
    """
    best = max(cluster, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
    best.emails = sorted({e for c in cluster for e in c.emails})
    best.tels   = sorted({t for c in cluster for t in c.tels})

    # Org / title / bday — take from whichever card has it if best doesn't
    if not best.org:
        for c in cluster:
            if c.org:
                best.org = c.org
                break
    if not best.title:
        for c in cluster:
            if c.title:
                best.title = c.title
                break

    # Categories: union across sources, log any conflicts
    merged_cats, conflict = _merge_categories(cluster)
    if merged_cats:
        before = set(best.categories)
        best.categories = sorted(set(best.categories) | set(merged_cats))
        gained = set(best.categories) - before
        if gained:
            if conflict:
                best.log_change(
                    f"Categories merged (conflict resolved by union): {', '.join(sorted(best.categories))}"
                )
            else:
                best.log_change(
                    f"Categories carried over from source: {', '.join(sorted(gained))}"
                )

    merged_names = [c.fn for c in cluster if c.fn and c.fn != best.fn]
    if len(cluster) > 1:
        best.log_change(
            f"Auto-merged {len(cluster)} duplicate(s)"
            + (f" (also seen as: {', '.join(merged_names)})" if merged_names else "")
        )

    return best


def merge_cluster_interactive(cluster: list[Card], idx: int = 0, total: int = 0) -> Card:
    return pick_merge(cluster, idx=idx, total=total)
