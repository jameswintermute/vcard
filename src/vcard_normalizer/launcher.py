from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .config import ensure_workspace
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

def _list_raw_files(paths) -> list[Path]:
    files = sorted([p for p in paths.raw_dir.glob("*.vcf") if p.is_file()])
    return files

def _pick_from_raw(paths) -> list[Path]:
    while True:
        files = _list_raw_files(paths)
        if not files:
            console.print(f"[yellow]No .vcf files found in[/] [bold]{paths.raw_dir}[/].")
            console.print("Drop files there, then press 'r' to refresh, or 'q' to go back.")
        else:
            table = Table(title=f"cards-raw ({paths.raw_dir})", show_lines=True)
            table.add_column("#", style="cyan", no_wrap=True)
            table.add_column("File", style="bold")
            for i, f in enumerate(files, 1):
                table.add_row(str(i), f.name)
            console.print(table)
            console.print("Type numbers (e.g., 1 or 1,3,5), 'r' to refresh, or 'q' to cancel.")

        choice = Prompt.ask("Select").strip().lower()
        if choice in {"q", "quit"}:
            return []
        if choice == "r":
            console.clear()
            continue
        if not files:
            continue
        try:
            picks = [int(x.strip()) for x in choice.split(",") if x.strip()]
            selected = [files[i-1] for i in picks if 1 <= i <= len(files)]
            if selected:
                return selected
        except Exception:
            pass
        console.print("[red]Invalid selection[/red]. Try again.")


def _cleanup_check(files: list[Path], settings, paths) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    before = [(c.fn, list(c.tels), [getattr(a, "country", None) for a in c.addresses]) for c in cards]

    normalize_phones_in_cards(cards, default_region=settings.default_region, infer_from_adr=True)
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

    if Confirm.ask("Save a cleaned copy to cards-clean/?", default=False):
        from datetime import date
        iso = date.today().isoformat()
        out = paths.clean_dir / f"{iso}-Cleaned-{settings.owner_name.replace(' ', '-')}.vcf"
        n = export_vcards(cards, out, target_version="4.0")
        console.print(f"[green]Wrote {n} contact(s) -> {out}[/green]")


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



def _banner() -> None:
    banner = r"""
 .----------------.  .----------------.  .----------------.  .----------------.  .----------------.
| .--------------. || .--------------. || .--------------. || .--------------. || .--------------. |
| | ____   ____  | || |     ______   | || |      __      | || |  _______     | || |  ________    | |
| ||_  _| |_  _| | || |   .' ___  |  | || |     /  \     | || | |_   __ \    | || | |_   ___ `.  | |
| |  \ \   / /   | || |  / .'   \_|  | || |    / /\ \    | || |   | |__) |   | || |   | |   `. \ | |
| |   \ \ / /    | || |  | |         | || |   / ____ \   | || |   |  __ /    | || |   | |    | | | |
| |    \ ' /     | || |  \ `.___.'\  | || | _/ /    \ \_ | || |  _| |  \ \_  | || |  _| |___.' / | |
| |     \_/      | || |   `._____.'  | || ||____|  |____|| || | |____| |___| | || | |________.'  | |
| |              | || |              | || |              | || |              | || |              | |
| '--------------' || '--------------' || '--------------' || '--------------' || '--------------' |
 '----------------'  '----------------'  '----------------'  '----------------'  '----------------'
"""
    console.print(banner.strip("\n"), style="bold cyan")
    console.print()
    console.print(Panel.fit(" VCard Cleaner & Dedupe  •  v0.1.1  •  Python ", style="magenta", border_style="bright_black", padding=(0, 2)))
    console.print()



def _analyze(files: list[Path]) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    clusters = find_duplicate_clusters(cards)
    dup_groups = sum(1 for c in clusters if len(c) > 1)

    t = Table(title="Analysis Summary", show_lines=True)
    t.add_column("Metric", style="cyan", no_wrap=True)
    t.add_column("Value", style="bold")
    t.add_row("Files", str(len(files)))
    t.add_row("Parsed cards", str(len(cards)))
    t.add_row("Potential duplicate groups", str(dup_groups))
    console.print(t)



def _merge(files: list[Path], owner_name: str, paths) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    stripper = DefaultStripper()
    cards = [stripper.strip(c) for c in cards]

    if Confirm.ask("Normalize phones & ensure country in ADR before merging?", default=True):
        normalize_phones_in_cards(cards, default_region="GB", infer_from_adr=True)
        ensure_country_in_addresses(cards)
        classify_entities(cards)

    clusters = find_duplicate_clusters(cards)
    merged: list = []
    for cluster in clusters:
        merged.append(merge_cluster_interactive(cluster) if len(cluster) > 1 else cluster[0])

    from datetime import date
    iso = date.today().isoformat()
    out = (paths.clean_dir / f"{iso}-Contacts-of-{owner_name.replace(' ', '-')}.vcf")
    n = export_vcards(merged, out, target_version="4.0")
    console.print(f"[green]Wrote {n} contact(s) -> {out}[/green]")



def _export_by_categories(files: list[Path], owner_name: str, paths) -> None:
    vcards = read_vcards_from_files(files)
    cards = normalize_cards(vcards)
    stripper = DefaultStripper()
    cards = [stripper.strip(c) for c in cards]

    cats = Prompt.ask("Enter comma-separated categories to include (case-sensitive)", default="")
    wanted = {c.strip() for c in cats.split(",") if c.strip()}
    if not wanted:
        console.print("[yellow]No categories provided; nothing to export[/yellow]")
        return

    filtered = [c for c in cards if set(c.categories) & wanted]

    from datetime import date
    iso = date.today().isoformat()
    out = (paths.clean_dir / f"{iso}-Contacts-of-{owner_name.replace(' ', '-')}-CATS.vcf")
    n = export_vcards(filtered, out, target_version="4.0")
    console.print(f"[green]Wrote {n} contact(s) -> {out}[/green]")


def main() -> None:
    paths, settings = ensure_workspace()
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
            files = _pick_from_raw(paths)
            if files:
                _analyze(files)

        elif choice == "2":
            files = _pick_from_raw(paths)
            if files:
                owner = Prompt.ask("Owner name for output filename", default=settings.owner_name)
                _merge(files, owner, paths)

        elif choice == "3":
            files = _pick_from_raw(paths)
            if files:
                owner = Prompt.ask("Owner name for output filename", default=settings.owner_name)
                _export_by_categories(files, owner, paths)

        elif choice == "4":
            files = _pick_from_raw(paths)
            if files:
                _cleanup_check(files, settings, paths)

        elif choice == "5":
            _deps_check()

        else:
            console.print("[red]Unknown option[/red]")

        if not Confirm.ask("\nReturn to menu?", default=True):
            break


if __name__ == "__main__":
    main()
