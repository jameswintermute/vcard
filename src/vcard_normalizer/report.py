from __future__ import annotations

from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from .model import Card

console = Console()


def _count_changes(cards: list[Card], keyword: str) -> int:
    return sum(1 for c in cards for chg in c._changes if keyword.lower() in chg.lower())


def print_summary(
    *,
    input_count: int,
    output_count: int,
    duplicate_clusters: int,
    cards: list[Card],
    out_path: Path,
    source_counts: dict[str, int] | None = None,
) -> None:
    """Print a rich summary table after processing."""
    console.print()
    console.print(Rule("[bold cyan]Processing Report[/bold cyan]"))

    # ── Source breakdown ───────────────────────────────────────────────────────
    if source_counts and len(source_counts) > 1:
        src_table = Table(show_header=True, box=None, padding=(0, 2))
        src_table.add_column("Source file", style="dim")
        src_table.add_column("Cards read", style="bold")
        for src, count in sorted(source_counts.items()):
            src_table.add_row(src, str(count))
        console.print(src_table)
        console.print()

    # ── Top-line stats ─────────────────────────────────────────────────────────
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold green")

    table.add_row("Contacts read in", str(input_count))
    table.add_row("Contacts written out", str(output_count))
    merged_count = input_count - output_count
    if merged_count > 0:
        table.add_row("Duplicates merged away", str(merged_count))
    table.add_row("Duplicate clusters found", str(duplicate_clusters))

    phones_fixed = _count_changes(cards, "Phone(s) reformatted")
    if phones_fixed:
        table.add_row("Contacts with phones reformatted", str(phones_fixed))

    photos_stripped = _count_changes(cards, "Stripped")
    if photos_stripped:
        table.add_row("Contacts with photos/proprietary stripped", str(photos_stripped))

    auto_tagged = _count_changes(cards, "Auto-tagged categories")
    if auto_tagged:
        table.add_row("Contacts auto-tagged with categories", str(auto_tagged))

    table.add_row("Output file", str(out_path))

    console.print(table)


def print_diff(cards: list[Card]) -> None:
    """Print a per-card change log for contacts that were modified."""
    changed = [c for c in cards if c._changes]
    if not changed:
        console.print("[dim]No per-contact changes to show.[/dim]")
        return

    console.print()
    console.print(Rule(f"[bold]Changes ({len(changed)} contact(s))[/bold]"))

    for c in changed:
        label = c.fn or c.org or "Unnamed"
        sources = (
            f" [dim](from: {', '.join(c._source_files)})[/dim]"
            if c._source_files else ""
        )
        console.print(f"  [bold cyan]{label}[/bold cyan]{sources}")
        for chg in c._changes:
            console.print(f"    [dim]·[/dim] {chg}")

    console.print()


def write_diff_file(cards: list[Card], path: Path) -> None:
    """Write a plain-text diff/change log alongside the output VCF."""
    changed = [c for c in cards if c._changes]
    lines: list[str] = [
        "vcard-normalizer — change log",
        "=" * 40,
        f"Contacts modified: {len(changed)}",
        "",
    ]
    for c in changed:
        label = c.fn or c.org or "Unnamed"
        sources = f"  (sources: {', '.join(c._source_files)})" if c._source_files else ""
        lines.append(f"{label}:{sources}")
        for chg in c._changes:
            lines.append(f"  - {chg}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def build_source_counts(
    raw_pairs: list[tuple[object, str]],
) -> dict[str, int]:
    """Count how many cards came from each source file."""
    return dict(Counter(label for _, label in raw_pairs))
