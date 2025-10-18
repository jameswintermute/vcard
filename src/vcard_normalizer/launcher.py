from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .dedupe import find_duplicate_clusters, merge_cluster_interactive
from .exporter import export_vcards
from .formatters import (
    classify_entities,
    ensure_country_in_addresses,
    normalize_phones_in_cards,
)
from .io import read_vcards_from_files
from .normalize import normalize_cards
from .proprietary import DefaultStripper

console = Console()

def _banner() -> None:
    banner = """
 .----------------.  .----------------.  .----------------.  .----------------.  .----------------. 
| .--------------. || .--------------. || .--------------. || .--------------. || .--------------. |
| | ____   ____  | || |     ______   | || |      __      | || |  _______     | || |  ________    | |
| ||_  _| |_  _| | || |   .' ___  |  | || |     /  \\     | || | |_   __ \\    | || | |_   ___ `.  | |
| |  \\ \\   / /   | || |  / .'   \\_|  | || |    / /\\ \\    | || |   | |__) |   | || |   | |   `. \\ | |
| |   \\ \\ / /    | || |  | |         | || |   / ____ \\   | || |   |  __ /    | || |   | |    | | | |
| |    \\ ' /     | || |  \\ `.___.'\\  | || | _/ /    \\ \\_ | || |  _| |  \\ \\_  | || |  _| |___.' / | |
| |     \\_/      | || |   `._____.'  | || ||____|  |____|| || | |____| |___| | || | |________.'  | |
| |              | || |              | || |              | || |              | || |              | |
| '--------------' || '--------------' || '--------------' || '--------------' || '--------------' |
 '----------------'  '----------------'  '----------------'  '----------------'  '----------------'  
"""
    console.print(banner.strip("\n"), style="bold cyan")
    console.print()
    console.print(
        Panel.fit(
            " VCard Cleaner & Dedupe  •  v0.1.1  •  Python ",
            style="magenta",
            border_style="bright_black",
            padding=(0, 2),
        )
    )
    console.print()


def _pick_files(prompt: str) -> list[Path]:
    pat = Prompt.ask(prompt + "\nEnter one or more globs (comma separated)", default="*.vcf")
    globs = [g.strip() for g in pat.split(",") if g.strip()]
    files: list[Path] = []
    for g in globs:
        files.extend(Path().glob(g))
    files = [f for f in files if f.is_file() and f.suffix.lower() == ".vcf"]
    if not files:
        console.print("[red]No .vcf files matched[/red]")
    else:
        console.print(f"[green]Matched {len(files)} file(s)[/green]")
    return files


def _analyze(files: list[Path]) -> None:
    cards = read_vcards_from_files(files)
    ncards = normalize_cards(cards)
    DefaultStripper().strip(ncards[0]) if ncards else None  # noop to ensure no crash

    clusters = find_duplicate_clusters(ncards)
    dup_groups = sum(1 for c in clusters if len(c) > 1)

    # summary
    t = Table(title="Analysis Summary", show_lines=True)
    t.add_column("Metric", style="cyan", no_wrap=True)
    t.add_column("Value", style="bold")
    t.add_row("Files", str(len(files)))
    t.add_row("Parsed cards", str(len(ncards)))
    t.add_row("Potential duplicate groups", str(dup_groups))
    console.print(t)


def _merge(files: list[Path], owner_name: str) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    stripper = DefaultStripper()
    cards = [stripper.strip(c) for c in cards]

    # Optional cleaners before merge
    if Confirm.ask("Normalize phones & ensure country in ADR before merging?", default=True):
        normalize_phones_in_cards(cards, default_region="GB", infer_from_adr=True)
        ensure_country_in_addresses(cards)
        classify_entities(cards)

    clusters = find_duplicate_clusters(cards)
    merged: list = []
    for cluster in clusters:
        merged.append(merge_cluster_interactive(cluster) if len(cluster) > 1 else cluster[0])

    iso = __import__("datetime").date.today().isoformat()
    out = Path(f"{iso}-Contacts-of-{owner_name.replace(' ', '-')}.vcf")
    n = export_vcards(merged, out, target_version="4.0")
    console.print(f"[green]Wrote {n} contact(s) -> {out}[/green]")


def _export_by_categories(files: list[Path], owner_name: str) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    stripper = DefaultStripper()
    cards = [stripper.strip(c) for c in cards]

    # Prompt categories to include
    cats = Prompt.ask("Enter comma-separated categories to include (case-sensitive)", default="")
    wanted = {c.strip() for c in cats.split(",") if c.strip()}
    if not wanted:
        console.print("[yellow]No categories provided; nothing to export[/yellow]")
        return

    filtered = [c for c in cards if set(c.categories) & wanted]
    iso = __import__("datetime").date.today().isoformat()
    out = Path(f"{iso}-Contacts-of-{owner_name.replace(' ', '-')}-CATS.vcf")
    n = export_vcards(filtered, out, target_version="4.0")
    console.print(f"[green]Wrote {n} contact(s) -> {out}[/green]")


def _cleanup_check(files: list[Path]) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    before = [(c.fn, list(c.tels), [getattr(a, "country", None) for a in c.addresses]) for c in cards]

    normalize_phones_in_cards(cards, default_region="GB", infer_from_adr=True)
    ensure_country_in_addresses(cards)
    classify_entities(cards)

    # show a small diff-like preview
    table = Table(title="Cleanup Preview (first 10)", show_lines=True)
    table.add_column("Name", style="bold")
    table.add_column("Phones (before)")
    table.add_column("Phones (after)")
    table.add_column("Countries (after)")
    for (name, tels_before, _), c in list(zip(before, cards, strict=False))[:10]:
        tels_after = c.tels
        countries = [a.country or "" for a in c.addresses]
        table.add_row(name or "", "\n".join(tels_before), "\n".join(tels_after), "\n".join(countries))
    console.print(table)
    console.print("[cyan]No files were written (dry run). Use merge/export flows to save changes.[/cyan]")


def _deps_check() -> None:
    from importlib.metadata import PackageNotFoundError, version

    rows: list[tuple[str, str]] = []
    for pkg in ("typer", "rich", "vobject", "rapidfuzz", "phonenumberslite"):
        try:
            rows.append((pkg, version(pkg)))
        except PackageNotFoundError:
            rows.append((pkg, "NOT INSTALLED"))
    t = Table(title="Dependency Checker")
    t.add_column("Package", style="cyan")
    t.add_column("Version", style="bold")
    for r in rows:
        t.add_row(*r)
    console.print(t)


def main() -> None:
    while True:
        console.clear()
        _banner()
        console.print(Text("Choose an option:", style="bold"))
        console.print(Text("\n### Section 1 — Core", style="magenta"))
        console.print("  1) Import and analyze a vCard file")
        console.print("  2) Select multiple vCard files and merge (interactive)")
        console.print("  3) Export selected categories from one or more vCard files")

        console.print(Text("\n### Section 2 — Cleanup", style="magenta"))
        console.print("  4) Check formats (phones, addresses) — dry run")

        console.print(Text("\n### Section 3 — Support", style="magenta"))
        console.print("  5) Dependency checker")
        console.print("\n  q) Quit\n")

        choice = Prompt.ask("Option", default="q").strip().lower()
        if choice in {"q", "quit"}:
            break

        if choice == "1":
            files = _pick_files("Analyze which vCard file(s)?")
            if files:
                _analyze(files)

        elif choice == "2":
            files = _pick_files("Select vCard files to merge")
            if files:
                owner = Prompt.ask("Owner name for output filename", default="James")
                _merge(files, owner)

        elif choice == "3":
            files = _pick_files("Select vCard files to filter by category")
            if files:
                owner = Prompt.ask("Owner name for output filename", default="James")
                _export_by_categories(files, owner)

        elif choice == "4":
            files = _pick_files("Select vCard files to cleanup-check")
            if files:
                _cleanup_check(files)

        elif choice == "5":
            _deps_check()

        else:
            console.print("[red]Unknown option[/red]")

        if not Confirm.ask("\nReturn to menu?", default=True):
            break


if __name__ == "__main__":
    main()
