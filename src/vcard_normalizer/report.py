from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .model import Card

console = Console()

# ── Palette ────────────────────────────────────────────────────────────────────
_ACCENT  = "#4d9fff"
_GREEN   = "#3ecf8e"
_AMBER   = "#f0a500"
_RED     = "#f05c5c"
_PURPLE  = "#b07fff"
_TEXT    = "#c9d1e0"
_MID     = "#8896af"
_DIM     = "#546075"
_BORDER  = "#2a3347"


def _count_changes(cards: list[Card], keyword: str) -> int:
    return sum(1 for c in cards for chg in c._changes if keyword.lower() in chg.lower())


def _stat_panel(value: str, label: str, colour: str) -> Panel:
    body = Text()
    body.append(f"{value}\n", style=f"bold {colour}")
    body.append(label, style=f"dim {_DIM}")
    return Panel(body, border_style=_BORDER, padding=(0, 2), expand=True)


def print_summary(
    *,
    input_count: int,
    output_count: int,
    duplicate_clusters: int,
    cards: list[Card],
    out_path: Path,
    source_counts: dict[str, int] | None = None,
) -> None:

    phones_fixed  = _count_changes(cards, "Phone(s) reformatted")
    auto_tagged   = _count_changes(cards, "Auto-tagged categories")
    merged_away   = input_count - output_count

    console.print()
    console.print(Text("  MERGE SUMMARY", style=f"dim {_DIM}"))
    console.print()

    # ── 2×2 stat grid ─────────────────────────────────────────────────────────
    row1 = Columns([
        _stat_panel(str(output_count),  "contacts written",   _ACCENT),
        _stat_panel(str(merged_away),   "duplicates merged",  _GREEN),
    ], equal=True, expand=True)
    row2 = Columns([
        _stat_panel(str(phones_fixed),  "phones reformatted", _TEXT),
        _stat_panel(str(auto_tagged),   "auto-tagged",        _TEXT),
    ], equal=True, expand=True)

    console.print(row1)
    console.print(row2)
    console.print()

    # ── Source breakdown (if multiple) ────────────────────────────────────────
    if source_counts and len(source_counts) > 1:
        src_parts = Text()
        for i, (src, count) in enumerate(sorted(source_counts.items())):
            if i:
                src_parts.append("   ", style="")
            src_parts.append(src, style=f"{_MID}")
            src_parts.append(f"  {count}", style=f"bold {_TEXT}")
        console.print(Panel(
            src_parts,
            title=Text("SOURCES READ", style=f"dim {_DIM}"),
            title_align="left",
            border_style=_BORDER,
            padding=(0, 1),
        ))
        console.print()

    # ── Change log (last 8 changed contacts) ─────────────────────────────────
    changed = [c for c in cards if c._changes]
    if changed:
        console.print(Text("  RECENT CHANGES", style=f"dim {_DIM}"))
        console.print()
        for c in changed[-8:]:
            label = (c.fn or c.org or "Unnamed")[:40]
            # Classify the dominant change type for colour
            chg_text = " ".join(c._changes).lower()
            if "merged" in chg_text:
                icon, colour = "⟐", _ACCENT
                tag = f"merged ×{len([x for x in c._changes if 'merged' in x.lower()])}"
            elif "phone" in chg_text:
                icon, colour = "✆", _GREEN
                tag = "phone reformatted"
            elif "categor" in chg_text:
                icon, colour = "◈", _PURPLE
                cats = sorted({
                    cat for chg in c._changes if "categor" in chg.lower()
                    for cat in chg.split(":")[-1].strip().split(", ")
                    if cat
                })
                tag = ", ".join(cats[:3])
            elif "stripped" in chg_text:
                icon, colour = "✂", _AMBER
                tag = "proprietary stripped"
            else:
                icon, colour = "·", _DIM
                tag = c._changes[0][:30]

            row = Text()
            row.append(f"  {icon} ", style=f"bold {colour}")
            row.append(f"{label:<38}", style=_TEXT)
            row.append(f"  {tag}", style=f"dim {colour}")
            console.print(row)
        console.print()

    # ── Success banner ─────────────────────────────────────────────────────────
    if str(out_path) != "<dry-run>":
        body = Text()
        body.append("✓  Written successfully\n", style=f"bold {_GREEN}")
        body.append(str(out_path), style=f"dim {_MID}")
        console.print(Panel(
            body,
            border_style=_GREEN,
            padding=(0, 2),
        ))


def print_diff(cards: list[Card]) -> None:
    changed = [c for c in cards if c._changes]
    if not changed:
        console.print(Text("  No per-contact changes to show.", style=f"dim {_DIM}"))
        return

    console.print()
    console.print(Text(f"  CHANGES  {len(changed)} contact(s)", style=f"dim {_DIM}"))
    console.print()

    for c in changed:
        label   = c.fn or c.org or "Unnamed"
        sources = f"  {', '.join(c._source_files)}" if c._source_files else ""
        header  = Text()
        header.append(f"  {label}", style=f"bold {_TEXT}")
        header.append(sources, style=f"dim {_DIM}")
        console.print(header)
        for chg in c._changes:
            console.print(Text(f"    · {chg}", style=f"dim {_MID}"))
    console.print()


def write_diff_file(cards: list[Card], path: Path) -> None:
    changed = [c for c in cards if c._changes]
    lines: list[str] = [
        "vcard-normalizer — change log",
        "=" * 40,
        f"Contacts modified: {len(changed)}",
        "",
    ]
    for c in changed:
        label   = c.fn or c.org or "Unnamed"
        sources = f"  (sources: {', '.join(c._source_files)})" if c._source_files else ""
        lines.append(f"{label}:{sources}")
        for chg in c._changes:
            lines.append(f"  - {chg}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_source_counts(raw_pairs: list[tuple[object, str]]) -> dict[str, int]:
    return dict(Counter(label for _, label in raw_pairs))
