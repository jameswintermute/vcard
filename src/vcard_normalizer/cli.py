from __future__ import annotations

import glob
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import ensure_workspace
from .dedupe import find_duplicate_clusters, merge_cluster_auto, merge_cluster_interactive
from .exporter import export_vcards
from .formatters import (
    _DELETE_SENTINEL,
    auto_tag_categories,
    classify_entities,
    ensure_country_in_addresses,
    normalize_phones_in_cards,
    prompt_categories_interactive,
    prompt_review_uncategorised,
)
from .io import collect_merge_sources, read_vcards_from_files
from .normalize import normalize_cards
from .proprietary import DefaultStripper
from .report import build_source_counts, print_diff, print_summary, write_diff_file

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="vcard-normalizer: clean, merge, and export address books from multiple sources.",
)
console = Console()


# ── Shared pipeline ────────────────────────────────────────────────────────────

def _run_pipeline(
    files: list[Path],
    owner_name: str,
    output: Path | None,
    interactive: bool,
    keep_unknown: bool,
    prefer_v: str,
    default_region: str,
    auto_categories: bool,
    dry_run: bool,
    diff: bool,
    write_changelog: bool,
) -> None:
    """Core processing pipeline shared by both `merge` and `ingest` commands."""

    if not files:
        console.print("[bold red]No .vcf files found.[/bold red]")
        raise typer.Exit(code=2)

    # ── 1. Read ────────────────────────────────────────────────────────────────
    console.print(f"\n[bold]Reading {len(files)} file(s)…[/bold]")
    for f in files:
        console.print(f"  [dim]{f.name}[/dim]")

    raw_pairs = read_vcards_from_files(files)
    input_count = len(raw_pairs)
    source_counts = build_source_counts(raw_pairs)
    console.print(
        f"  Parsed [bold]{input_count}[/bold] vCard(s) from "
        f"{len(source_counts)} source file(s)\n"
    )

    # ── 2. Normalise + strip ───────────────────────────────────────────────────
    cards = normalize_cards(raw_pairs)
    stripper = DefaultStripper(keep_unknown=keep_unknown)
    cards = [stripper.strip(c) for c in cards]

    # ── 3. Phone normalisation ─────────────────────────────────────────────────
    console.print(f"  Normalising phones (region: [bold]{default_region}[/bold])…")
    normalize_phones_in_cards(cards, default_region=default_region, infer_from_adr=True)

    # ── 4. KIND classification ─────────────────────────────────────────────────
    classify_entities(cards)

    # ── 5. Auto-tag categories ─────────────────────────────────────────────────
    if auto_categories:
        auto_tag_categories(cards)

    # ── 6. Deduplication ──────────────────────────────────────────────────────
    clusters = find_duplicate_clusters(cards)
    dup_clusters = [cl for cl in clusters if len(cl) > 1]
    cross_source = sum(
        1 for cl in dup_clusters
        if len({s for c in cl for s in c._source_files}) > 1
    )
    console.print(
        f"  Duplicate clusters: [bold]{len(dup_clusters)}[/bold]"
        + (f"  ([cyan]{cross_source} cross-source[/cyan])" if cross_source else "")
    )

    merged: list = []
    dup_clusters_list = [cl for cl in clusters if len(cl) > 1]
    n_interactive = len(dup_clusters_list) if interactive else 0
    interactive_idx = 0
    for cluster in clusters:
        if len(cluster) == 1:
            merged.append(cluster[0])
            continue
        if interactive:
            interactive_idx += 1
            merged.append(merge_cluster_interactive(cluster, idx=interactive_idx, total=n_interactive))
        else:
            merged.append(merge_cluster_auto(cluster))

    # Restore source provenance on auto-merged cards
    for cluster in dup_clusters:
        cluster_emails = {e for c in cluster for e in c.emails}
        cluster_tels = {t for c in cluster for t in c.tels}
        for m in merged:
            if set(m.emails) & cluster_emails or set(m.tels) & cluster_tels:
                all_sources = sorted({s for c in cluster for s in c._source_files})
                m._source_files = all_sources
                if len(all_sources) > 1:
                    m.log_change(f"Merged from sources: {', '.join(all_sources)}")
                break

    # ── 7. Interactive country / category review ───────────────────────────────
    if interactive:
        ensure_country_in_addresses(merged)
        prompt_categories_interactive(merged)

    # ── 7b. Post-processing: offer to review uncategorised contacts ────────────
    # Runs in both interactive and non-interactive modes — it only fires if
    # there are uncategorised contacts AND the user says yes.
    if not dry_run:
        prompt_review_uncategorised(merged)

    # ── 7c. Remove any contacts marked for deletion during review ──────────────
    deleted_count = sum(1 for c in merged if _DELETE_SENTINEL in c.categories)
    if deleted_count:
        merged = [c for c in merged if _DELETE_SENTINEL not in c.categories]
        console.print(f"  [red]Deleted {deleted_count} contact(s) during review.[/red]")

    # ── 8. Dry-run short-circuit ───────────────────────────────────────────────
    if dry_run:
        console.print("\n[yellow bold]Dry-run mode — no files written.[/yellow bold]")
        print_summary(
            input_count=input_count,
            output_count=len(merged),
            duplicate_clusters=len(dup_clusters),
            cards=merged,
            out_path=Path("<dry-run>"),
            source_counts=source_counts,
        )
        if diff:
            print_diff(merged)
        return

    # ── 9. Output path ─────────────────────────────────────────────────────────
    out_path = output
    if out_path is None:
        iso = date.today().isoformat()
        safe_owner = owner_name.replace(" ", "-")
        out_path = Path("cards-clean") / f"{iso}-Contacts-of-{safe_owner}.vcf"

    # ── 10. Export ────────────────────────────────────────────────────────────
    count = export_vcards(merged, out_path, target_version=prefer_v)
    console.print(f"\n[bold green]✓ Wrote {count} contact(s) → {out_path}[/bold green]")

    # ── 11. Report ────────────────────────────────────────────────────────────
    print_summary(
        input_count=input_count,
        output_count=count,
        duplicate_clusters=len(dup_clusters),
        cards=merged,
        out_path=out_path,
        source_counts=source_counts,
    )

    if diff:
        print_diff(merged)

    if write_changelog:
        changelog_path = out_path.with_suffix(".changes.txt")
        write_diff_file(merged, changelog_path)
        console.print(f"[dim]Change log → {changelog_path}[/dim]")


# ── `merge` command ────────────────────────────────────────────────────────────

@app.command()
def merge(
    merge_dir: Path = typer.Option(
        Path("cards-merge"),
        "--dir", "-d",
        help="Folder containing source .vcf files (default: cards-merge/)",
    ),
    owner_name: str | None = typer.Option(
        None, "--owner-name", "-n",
        help="Your name for the output filename. Falls back to local/vcard.conf.",
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Explicit output .vcf path"),
    region: str | None = typer.Option(
        None, "--region", "-r",
        help="Phone region ISO-2 code (e.g. GB, US). Falls back to local/vcard.conf.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Auto-merge all duplicates"),
    keep_unknown: bool = typer.Option(False, help="Keep unknown X-* fields"),
    prefer_v: str = typer.Option("4.0", help="Target vCard version (3.0 or 4.0)"),
    no_auto_categories: bool = typer.Option(False, "--no-auto-categories"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing any files"),
    diff: bool = typer.Option(False, "--diff", help="Print per-contact change log"),
    write_changelog: bool = typer.Option(False, "--write-changelog", help="Write .changes.txt log"),
) -> None:
    """Merge contact exports from iCloud, Protonmail, Google, etc. into one clean file.

    \b
    Workflow:
      1. Export contacts from each source as a .vcf file
      2. Drop them into  cards-merge/
      3. Run:  vcard-normalize merge

    The tool will show you what it found and ask for confirmation before
    processing. Settings (owner name, phone region) are read from
    local/vcard.conf so you rarely need to pass flags.
    """

    # ── Load config for defaults ───────────────────────────────────────────────
    _, settings = ensure_workspace()
    effective_owner = owner_name or settings.owner_name
    effective_region = region or settings.default_region

    # ── Discover source files ──────────────────────────────────────────────────
    files = collect_merge_sources(merge_dir)

    if not files:
        console.print(Panel(
            f"[bold red]No .vcf files found in [white]{merge_dir}/[/white][/bold red]\n\n"
            "Drop your exported contact files here and re-run:\n"
            f"  [dim]{merge_dir}/icloud.vcf[/dim]\n"
            f"  [dim]{merge_dir}/protonmail.vcf[/dim]\n"
            f"  [dim]{merge_dir}/google.vcf[/dim]   ← etc.",
            title="Nothing to merge",
            border_style="red",
        ))
        raise typer.Exit(code=2)

    # ── Confirmation screen ────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[bold cyan]vcard-normalize merge[/bold cyan]\n"
        f"Found [bold]{len(files)}[/bold] source file(s) in "
        f"[dim]{merge_dir}/[/dim]",
        border_style="cyan",
    ))

    # Show a table of what was found
    file_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    file_table.add_column("Source file")
    file_table.add_column("Size")
    file_table.add_column("Modified")
    for f in files:
        stat = f.stat()
        size_kb = stat.st_size / 1024
        from datetime import datetime
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        file_table.add_row(f.name, f"{size_kb:.1f} KB", mtime)
    console.print(file_table)

    console.print(f"\n  Owner name : [bold]{effective_owner}[/bold]")
    console.print(f"  Phone region: [bold]{effective_region}[/bold]")
    console.print(f"  Mode        : [bold]{'auto-merge' if no_interactive else 'interactive review'}[/bold]")
    if dry_run:
        console.print("  [yellow bold]Dry run — nothing will be written[/yellow bold]")
    console.print()

    # ── Ask to proceed (unless --yes) ─────────────────────────────────────────
    if not yes and not dry_run:
        proceed = typer.confirm("Proceed with merge?", default=True)
        if not proceed:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(code=0)

    # ── Run ────────────────────────────────────────────────────────────────────
    _run_pipeline(
        files=files,
        owner_name=effective_owner,
        output=output,
        interactive=not no_interactive,
        keep_unknown=keep_unknown,
        prefer_v=prefer_v,
        default_region=effective_region,
        auto_categories=not no_auto_categories,
        dry_run=dry_run,
        diff=diff,
        write_changelog=write_changelog,
    )


# ── `ingest` command ───────────────────────────────────────────────────────────

@app.command()
def ingest(
    input: list[str] = typer.Option(..., help="Glob(s) for .vcf input files"),
    owner_name: str = typer.Option(..., "--owner-name", "-n", help="Owner name for output filename"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Explicit output .vcf path"),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive"),
    keep_unknown: bool = typer.Option(False, help="Keep unknown X-* fields"),
    prefer_v: str = typer.Option("4.0", help="Target vCard version (3.0 or 4.0)"),
    default_region: str = typer.Option("GB", "--region", "-r", help="Default phone region (ISO-2)"),
    auto_categories: bool = typer.Option(True, "--auto-categories/--no-auto-categories"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    write_changelog: bool = typer.Option(False, "--write-changelog"),
) -> None:
    """Ingest .vcf files via explicit glob(s), normalise, deduplicate, and export."""
    files: list[Path] = []
    for g in input:
        files.extend([Path(p) for p in glob.glob(g, recursive=True)])
    files = [f for f in files if f.is_file() and f.suffix.lower() == ".vcf"]

    _run_pipeline(
        files=files,
        owner_name=owner_name,
        output=output,
        interactive=interactive,
        keep_unknown=keep_unknown,
        prefer_v=prefer_v,
        default_region=default_region,
        auto_categories=auto_categories,
        dry_run=dry_run,
        diff=diff,
        write_changelog=write_changelog,
    )


if __name__ == "__main__":
    app()
