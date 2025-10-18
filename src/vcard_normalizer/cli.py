from __future__ import annotations

import glob
from pathlib import Path

import typer
from rich.console import Console

from .dedupe import find_duplicate_clusters, merge_cluster_auto, merge_cluster_interactive
from .exporter import export_vcards
from .io import read_vcards_from_files
from .normalize import normalize_cards
from .proprietary import DefaultStripper

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

@app.command()
def ingest(
    input: list[str] = typer.Option(..., help="Glob(s) for .vcf files"),
    owner_name: str = typer.Option(..., "--owner-name", "-n", help="Owner name for output filename"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Explicit output .vcf path"),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", help="Interactive merge review"),
    keep_unknown: bool = typer.Option(False, help="Keep unknown X-* fields instead of stripping"),
    prefer_v: str = typer.Option("4.0", help="Target vCard version for export (3.0 or 4.0)"),
):
    """Ingest one or more VCFs, strip proprietary fields, normalize, de-duplicate, and export one file."""
    files: list[Path] = []
    for g in input:
        files.extend([Path(p) for p in glob.glob(g, recursive=True)])
    files = [f for f in files if f.is_file() and f.suffix.lower() == ".vcf"]
    if not files:
        raise typer.Exit(code=2)

    console.print(f"[bold]Reading {len(files)} files…[/bold]")
    cards = read_vcards_from_files(files)
    console.print(f"Parsed cards: {len(cards)}")

    cards = normalize_cards(cards)
    stripper = DefaultStripper(keep_unknown=keep_unknown)
    cards = [stripper.strip(c) for c in cards]

    clusters = find_duplicate_clusters(cards)
    console.print(f"Potential duplicate clusters: {len(clusters)}")

    merged = []
    for cluster in clusters:
        if len(cluster) == 1:
            merged.append(cluster[0])
            continue
        if interactive:
            merged.append(merge_cluster_interactive(cluster))
        else:
            merged.append(merge_cluster_auto(cluster))

    # Unique cards not part of any cluster >1 are already included; clusters handled above.
    # Export
    out_path = output
    if out_path is None:
        from datetime import date
        iso = date.today().isoformat()
        safe_owner = owner_name.replace(" ", "-")
        out_path = Path(f"{iso}-Contacts-of-{safe_owner}.vcf")
    count = export_vcards(merged, out_path, target_version=prefer_v)
    console.print(f"[green]Wrote {count} card(s) to {out_path}")


if __name__ == "__main__":
    app()
