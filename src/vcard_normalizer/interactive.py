from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text
from rich.table import Table

from .formatters import _DELETE_SENTINEL
from .model import Card
from ._similarity import similarity

console = Console()


class QuitReview(Exception):
    """Raised when the user presses q to save and exit mid-review."""

_ACCENT = "#4d9fff"
_GREEN  = "#3ecf8e"
_DIM    = "#546075"
_MID    = "#8896af"
_TEXT   = "#c9d1e0"
_AMBER  = "#f0a500"
_BORDER = "#2a3347"

# Similarity threshold above which we silently auto-union without asking
_AUTO_UNION_THRESHOLD = 95.0


def _progress_bar(done: int, total: int, width: int = 20) -> Text:
    filled = round(width * done / total) if total else 0
    bar = Text()
    bar.append("█" * filled,            style=_ACCENT)
    bar.append("░" * (width - filled),  style=f"dim {_DIM}")
    bar.append(f"  {done} / {total}",   style=f"dim {_DIM}")
    return bar


def _show_cluster(cluster: list[Card], idx: int, total: int, score: float) -> None:
    # Header row: progress + similarity score
    header = Text()
    header.append(f"  DUPLICATE REVIEW  ", style=f"dim {_DIM}")
    header.append_text(_progress_bar(idx - 1, total))
    header.append(f"   similarity {score:.0f}%", style=f"dim {_AMBER}" if score < 90 else f"dim {_GREEN}")
    console.print()
    console.print(header)
    console.print()

    table = Table(show_lines=True, border_style=_BORDER, header_style=f"dim {_DIM}")
    table.add_column("#",          justify="right", style=f"bold {_ACCENT}", no_wrap=True)
    table.add_column("Name",       style=f"bold {_TEXT}")
    table.add_column("Emails",     style=f"{_MID}")
    table.add_column("Phone",      style=f"{_MID}")
    table.add_column("Org",        style=f"dim {_MID}")
    table.add_column("Categories", style=f"{_AMBER}")

    for i, c in enumerate(cluster, 1):
        org_title = (c.org or "") + (" / " + c.title if c.org and c.title else (c.title or ""))
        cats = ", ".join(c.categories) if c.categories else ""
        kind_icon = "🏢" if c.kind == "org" else ("👤" if c.kind == "individual" else "❓")
        table.add_row(
            str(i),
            f"{kind_icon}  {c.fn or ''}",
            "\n".join(c.emails) if c.emails else "",
            "\n".join(c.tels)   if c.tels   else "",
            org_title.strip(),
            cats,
        )
    console.print(table)


def _is_effectively_identical(cluster: list[Card]) -> bool:
    """True if every card in the cluster shares all meaningful data fields.

    We auto-union without prompting when the only differences are trivial
    name variants (e.g. 'Jon' vs 'John'), since the user gains nothing from
    being asked — the union result is obviously correct.
    """
    if len(cluster) < 2:
        return True
    # Check pairwise similarity — all pairs must score ≥ threshold
    for i in range(len(cluster)):
        for j in range(i + 1, len(cluster)):
            if similarity(cluster[i], cluster[j]) < _AUTO_UNION_THRESHOLD:
                return False
    return True


def pick_merge(cluster: list[Card], idx: int = 0, total: int = 0) -> Card:
    """Interactively resolve a duplicate cluster.

    If all cards are effectively identical (similarity ≥ 95%) the union is
    applied silently without prompting.  Otherwise the user is shown the
    cluster table and asked to choose.
    """
    # Compute the representative similarity score for display
    score = similarity(cluster[0], cluster[1]) if len(cluster) >= 2 else 100.0

    # Auto-union truly identical clusters silently
    if _is_effectively_identical(cluster):
        result = _union(cluster)
        result.log_change(f"Auto-unioned {len(cluster)} identical duplicate(s) (score {score:.0f}%)")
        return result

    _show_cluster(cluster, idx, total, score)

    _RED = "#f05c5c"
    if len(cluster) == 2:
        choice = Prompt.ask(
            Text.assemble(
                Text("  › ", style=f"bold {_ACCENT}"),
                Text("Keep ", style=_TEXT),
                Text("1", style=f"bold {_ACCENT}"),
                Text(" / ", style=_DIM),
                Text("2", style=f"bold {_ACCENT}"),
                Text("  or  ", style=_TEXT),
                Text("u", style=f"bold {_GREEN}"),
                Text(" union", style=_TEXT),
                Text("  or  ", style=_TEXT),
                Text("d", style=f"bold {_RED}"),
                Text(" delete both", style=_TEXT),
                Text("  or  ", style=_TEXT),
                Text("q", style=f"dim {_DIM}"),
                Text(" save & quit", style=_TEXT),
            ),
            choices=["1", "2", "u", "d", "q"],
            default="u",
        )
    else:
        choice = Prompt.ask(
            Text.assemble(
                Text(f"  › Pick 1–{len(cluster)} or  ", style=_TEXT),
                Text("u", style=f"bold {_GREEN}"),
                Text(" union  ", style=_TEXT),
                Text("d", style=f"bold {_RED}"),
                Text(" delete  ", style=_TEXT),
                Text("q", style=f"dim {_DIM}"),
                Text(" save & quit", style=_TEXT),
            ),
            default="u",
        )

    if choice.lower() == "q":
        raise QuitReview()
    if choice.lower() == "u":
        return _union(cluster)
    if choice.lower() == "d":
        # Mark the best card with the delete sentinel — dedupe.py will filter it out
        best = max(cluster, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
        best.categories = [_DELETE_SENTINEL]
        best.log_change("Marked for deletion during duplicate review")
        console.print(Text("  ✗  Marked for deletion", style=f"bold #f05c5c"))
        return best
    try:
        base_idx = int(choice) - 1
    except Exception:
        base_idx = 0
    base_idx = max(0, min(base_idx, len(cluster) - 1))
    others = [c for i, c in enumerate(cluster) if i != base_idx]
    return _adopt(cluster[base_idx], *others)


def _union(cards: list[Card]) -> Card:
    base = max(cards, key=lambda c: (len(c.emails) + len(c.tels), len(c.fn or "")))
    for c in cards:
        base.emails     = sorted(set(base.emails) | set(c.emails))
        base.tels       = sorted(set(base.tels)   | set(c.tels))
        base.categories = sorted(set(base.categories) | set(c.categories))
        if not base.fn    and c.fn:    base.fn    = c.fn
        if not base.org   and c.org:   base.org   = c.org
        if not base.title and c.title: base.title = c.title
        if not base.bday  and c.bday:  base.bday  = c.bday
        if not base.uid   and c.uid:   base.uid   = c.uid
        if not base.kind  and c.kind:  base.kind  = c.kind
    return base


def _adopt(base: Card, *others: Card) -> Card:
    for c in others:
        base.emails     = sorted(set(base.emails) | set(c.emails))
        base.tels       = sorted(set(base.tels)   | set(c.tels))
        base.categories = sorted(set(base.categories) | set(c.categories))
        if not base.fn    and c.fn:    base.fn    = c.fn
        if not base.org   and c.org:   base.org   = c.org
        if not base.title and c.title: base.title = c.title
        if not base.bday  and c.bday:  base.bday  = c.bday
        if not base.uid   and c.uid:   base.uid   = c.uid
        if not base.kind  and c.kind:  base.kind  = c.kind
    return base
