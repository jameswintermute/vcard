from __future__ import annotations

import glob
from pathlib import Path

import typer
from rich.console import Console

from .dedupe import find_duplicate_clusters, merge_cluster_auto, merge_cluster_interactive
from .exporter import export_vcards
from .formatters import (
    auto_tag_categories,
    classify_entities,
    ensure_country_in_addresses,
    normalize_phones_in_cards,
    prompt_categories_interactive,
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
    """Core processing pipeline shared by both `ingest` and `merge` commands."""

    if not files:
        console.print("[bold red]No .vcf files found.[/bold red]")
        raise typer.Exit(code=2)

    # ── 1. Read all sources ────────────────────────────────────────────────────
    console.print(f"[bold]Reading {len(files)} file(s)…[/bold]")
    for f in files:
        console.print(f"  [dim]{f.name}[/dim]")

    raw_pairs = read_vcards_from_files(files)   # list[(vobject, source_label)]
    input_count = len(raw_pairs)
    source_counts = build_source_counts(raw_pairs)
    console.print(f"  Parsed [bold]{input_count}[/bold] vCard(s) from "
                  f"{len(source_counts)} source(s)")

    # ── 2. Normalise + strip (photos always removed) ───────────────────────────
    cards = normalize_cards(raw_pairs)
    stripper = DefaultStripper(keep_unknown=keep_unknown)
    cards = [stripper.strip(c) for c in cards]

    # ── 3. Phone normalisation ─────────────────────────────────────────────────
    console.print(f"  Normalising phones (default region: [bold]{default_region}[/bold])…")
    normalize_phones_in_cards(cards, default_region=default_region, infer_from_adr=True)

    # ── 4. KIND classification ─────────────────────────────────────────────────
    classify_entities(cards)

    # ── 5. Auto-tag categories ─────────────────────────────────────────────────
    if auto_categories:
        auto_tag_categories(cards)

    # ── 6. Deduplication ──────────────────────────────────────────────────────
    # Runs after phone normalisation so local and international formats match.
    clusters = find_duplicate_clusters(cards)
    dup_clusters = [cl for cl in clusters if len(cl) > 1]
    console.print(f"  Duplicate clusters: [bold]{len(dup_clusters)}[/bold]"
                  + (" (cross-source merges possible)" if len(source_counts) > 1 else ""))

    merged: list = []
    for cluster in clusters:
        if len(cluster) == 1:
            merged.append(cluster[0])
            continue
        if interactive:
            merged.append(merge_cluster_interactive(cluster))
        else:
            merged.append(merge_cluster_auto(cluster))

    # Union source labels onto merged cards so report shows provenance
    # (merge_cluster_auto picks a winner; restore all source labels)
    # This is best-effort — the interactive path already unions in pick_merge.
    for cluster in dup_clusters:
        # Find the winning card in merged (it will have one of the cluster's emails/tels)
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

    # ── 9. Determine output path ───────────────────────────────────────────────
    out_path = output
    if out_path is None:
        from datetime import date
        iso = date.today().isoformat()
        safe_owner = owner_name.replace(" ", "-")
        out_path = Path(f"{iso}-Contacts-of-{safe_owner}.vcf")

    # ── 10. Export ────────────────────────────────────────────────────────────
    count = export_vcards(merged, out_path, target_version=prefer_v)
    console.print(f"[green]Wrote {count} contact(s) → {out_path}[/green]")

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


# ── Common option definitions ──────────────────────────────────────────────────

def _common_options(fn):
    """Decorator that attaches the shared flags to both commands."""
    return fn


# ── `merge` command ────────────────────────────────────────────────────────────

@app.command()
def merge(
    merge_dir: Path = typer.Option(
        Path("cards-merge"),
        "--dir", "-d",
        help="Folder containing source .vcf files to merge (default: cards-merge/)",
    ),
    owner_name: str = typer.Option(..., "--owner-name", "-n", help="Your name for output filename"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Explicit output .vcf path"),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive"),
    keep_unknown: bool = typer.Option(False, help="Keep unknown X-* fields"),
    prefer_v: str = typer.Option("4.0", help="Target vCard version (3.0 or 4.0)"),
    default_region: str = typer.Option("GB", "--region", "-r", help="Default phone region (ISO-2)"),
    auto_categories: bool = typer.Option(True, "--auto-categories/--no-auto-categories"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing files"),
    diff: bool = typer.Option(False, "--diff", help="Print per-contact change log"),
    write_changelog: bool = typer.Option(False, "--write-changelog"),
) -> None:
    """Drop .vcf exports from iCloud, Protonmail, etc. into cards-merge/ then run this.

    Reads every .vcf in the merge directory, strips proprietary fields and photos,
    normalises phone numbers, deduplicates across all sources, and writes one
    clean consolidated vCard 4.0 file.

    \b
    Typical workflow:
      1. Export contacts from iCloud  → save as  cards-merge/icloud.vcf
      2. Export contacts from Proton  → save as  cards-merge/protonmail.vcf
      3. vcard-normalize merge --owner-name "James"
    """
    files = collect_merge_sources(merge_dir)
    if not files:
        console.print(
            f"[bold red]No .vcf files found in '{merge_dir}'.[/bold red]\n"
            f"Create the folder and drop your exported .vcf files into it, then re-run.\n"
            f"  mkdir -p {merge_dir}"
        )
        raise typer.Exit(code=2)

    console.print(
        f"[bold cyan]Merge mode[/bold cyan] — "
        f"found [bold]{len(files)}[/bold] source(s) in [dim]{merge_dir}/[/dim]"
    )
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


# ── `ingest` command (original, now delegates to shared pipeline) ──────────────

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
