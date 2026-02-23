from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from .model import Card

console = Console()


def _show_cluster(cluster: list[Card]) -> None:
    table = Table(title=f"Merge {len(cluster)} similar contacts", show_lines=True)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("FN", style="bold")
    table.add_column("Emails")
    table.add_column("Tels")
    table.add_column("Org/Title")
    for idx, c in enumerate(cluster, start=1):
        org = c.org or ""
        title = c.title or ""
        org_title = (org + (" / " if org and title else "") + title).strip()
        table.add_row(
            str(idx),
            c.fn or "",
            "\n".join(c.emails) if c.emails else "",
            "\n".join(c.tels) if c.tels else "",
            org_title,
        )
    console.print(table)


def pick_merge(cluster: list[Card]) -> Card:
    if len(cluster) == 2:
        _show_cluster(cluster)
        choice = Prompt.ask(
            "Pick base card to keep (1/2) or 'u' to union",
            choices=["1", "2", "u"],
            default="u",
        )
        if choice == "u":
            return _union(cluster)
        base_index = 0 if choice == "1" else 1
        other_index = 1 - base_index
        return _adopt(cluster[base_index], cluster[other_index])

    _show_cluster(cluster)
    choice = Prompt.ask("Pick base index or 'u' to union all", default="u")
    if choice.lower() == "u":
        return _union(cluster)
    try:
        base = int(choice) - 1
    except Exception:
        base = 0
    others = [c for i, c in enumerate(cluster) if i != base]
    return _adopt(cluster[base], *others)


def _union(cards: list[Card]) -> Card:
    base = max(cards, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
    for c in cards:
        base.emails = sorted(set(base.emails) | set(c.emails))
        base.tels = sorted(set(base.tels) | set(c.tels))
        if not base.fn and c.fn:
            base.fn = c.fn
        if not base.org and c.org:
            base.org = c.org
        if not base.title and c.title:
            base.title = c.title
        if not base.bday and c.bday:
            base.bday = c.bday
        if not base.uid and c.uid:
            base.uid = c.uid
        if not base.kind and c.kind:
            base.kind = c.kind
        if c.categories:
            base.categories = sorted(set(base.categories) | set(c.categories))
    return base


def _adopt(base: Card, *others: Card) -> Card:
    for c in others:
        base.emails = sorted(set(base.emails) | set(c.emails))
        base.tels = sorted(set(base.tels) | set(c.tels))
        if not base.fn and c.fn:
            base.fn = c.fn
        if not base.org and c.org:
            base.org = c.org
        if not base.title and c.title:
            base.title = c.title
        if not base.bday and c.bday:
            base.bday = c.bday
        if not base.uid and c.uid:
            base.uid = c.uid
        if not base.kind and c.kind:
            base.kind = c.kind
        if c.categories:
            base.categories = sorted(set(base.categories) | set(c.categories))
    return base
