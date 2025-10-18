from __future__ import annotations
from typing import List
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from .model import Card

console = Console()

def _show_cluster(cluster: List[Card]) -> None:
    table = Table(title=f"Merge {len(cluster)} similar contacts", show_lines=True)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("FN", style="bold")
    table.add_column("Emails")
    table.add_column("Tels")
    table.add_column("Org/Title")
    for idx, c in enumerate(cluster, start=1):
        table.add_row(
            str(idx),
            c.fn or "",
            "\n".join(c.emails) if c.emails else "",
            "\n".join(c.tels) if c.tels else "",
            f"{c.org or ''} / {c.title or ''}".strip(" / "),
        )
    console.print(table)

def pick_merge(cluster: List[Card]) -> Card:
    if len(cluster) == 2:
        _show_cluster(cluster)
        choice = Prompt.ask("Pick base card to keep (1/2) or 'u' to union", choices=["1","2","u"], default="u")
        if choice == "u":
            return _union(cluster)
        return _adopt(cluster[int(choice)-1], cluster[1 if choice=="1" else 0])
    else:
        _show_cluster(cluster)
        choice = Prompt.ask("Pick base index or 'u' to union all", default="u")
        if choice.lower() == "u":
            return _union(cluster)
        try:
            base = int(choice)-1
        except Exception:
            base = 0
        return _adopt(cluster[base], *[c for i,c in enumerate(cluster) if i!=base])

def _union(cards: List[Card]) -> Card:
    base = max(cards, key=lambda c: (len(c.emails)+len(c.tels), len((c.fn or ""))))
    for c in cards:
        base.emails = sorted(set(base.emails) | set(c.emails))
        base.tels = sorted(set(base.tels) | set(c.tels))
        base.org = base.org or c.org
        base.title = base.title or c.title
        base.bday = base.bday or c.bday
        base.uid = base.uid or c.uid
    return base

def _adopt(base: Card, *others: Card) -> Card:
    for c in others:
        base.emails = sorted(set(base.emails) | set(c.emails))
        base.tels = sorted(set(base.tels) | set(c.tels))
        if not base.fn and c.fn: base.fn = c.fn
        if not base.org and c.org: base.org = c.org
        if not base.title and c.title: base.title = c.title
        if not base.bday and c.bday: base.bday = c.bday
        if not base.uid and c.uid: base.uid = c.uid
    return base
