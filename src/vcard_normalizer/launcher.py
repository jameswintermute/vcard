"""vcard-start — guided main menu for the vCard normalizer."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

_ACCENT  = "#4d9fff"
_GREEN   = "#3ecf8e"
_AMBER   = "#f0a500"
_RED     = "#f05c5c"
_TEXT    = "#c9d1e0"
_MID     = "#8896af"
_DIM     = "#546075"
_BG3     = "#1c2230"
_BORDER  = "#2a3347"


def _run(*args: str) -> None:
    import os
    src_dir = str(Path(__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "vcard_normalizer.cli", *args]
    try:
        subprocess.run(cmd, check=False, env=env)
    except KeyboardInterrupt:
        pass


def _merge_sources() -> tuple[int, list[str]]:
    merge_dir = Path("cards-merge")
    if not merge_dir.is_dir():
        return 0, []
    vcfs = sorted(merge_dir.glob("*.vcf"))
    return len(vcfs), [f.name for f in vcfs]


def _latest_output() -> tuple[str, float] | None:
    clean_dir = Path("cards-clean")
    if not clean_dir.is_dir():
        return None
    vcfs = sorted(clean_dir.glob("*.vcf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not vcfs:
        return None
    v = vcfs[0]
    return v.name, v.stat().st_size / 1024


def _wordmark() -> None:
    t = Text()
    t.append("v", style=f"bold {_ACCENT}")
    t.append("card", style=f"bold {_TEXT}")
    t.append("  ·  ", style=f"{_DIM}")
    t.append("Address Book Cleaner", style=f"{_DIM}")
    console.print(t)
    console.print(Text("v0.2.0  ·  ready", style=f"dim {_DIM}"))
    console.print()


def _status_bar() -> None:
    n_src, src_names = _merge_sources()
    latest = _latest_output()

    if n_src == 0:
        src_body = Text("No files in cards-merge/", style=f"dim {_DIM}")
    else:
        src_body = Text()
        src_body.append(str(n_src), style=f"bold {_ACCENT}")
        src_body.append(f" file{'s' if n_src != 1 else ''}  ", style=f"{_TEXT}")
        src_body.append("  ".join(src_names), style=f"dim {_DIM}")

    src_panel = Panel(src_body, title=Text("SOURCES", style=f"dim {_DIM}"),
                      title_align="left", border_style=_BORDER, padding=(0, 1), expand=True)

    if latest is None:
        out_body = Text("No output yet", style=f"dim {_DIM}")
    else:
        name, kb = latest
        out_body = Text()
        out_body.append(name, style=f"bold {_GREEN}")
        out_body.append(f"  {kb:.1f} KB", style=f"dim {_DIM}")

    out_panel = Panel(out_body, title=Text("LAST OUTPUT", style=f"dim {_DIM}"),
                      title_align="left", border_style=_BORDER, padding=(0, 1), expand=True)

    console.print(Columns([src_panel, out_panel], equal=True, expand=True))
    console.print()


def _menu() -> None:
    def section(title: str) -> None:
        console.print(Text(f" {title}", style=f"dim {_DIM}"))

    def item(key: str, label: str, hint: str = "") -> None:
        line = Text()
        line.append(f" {key} ", style=f"bold {_ACCENT} on {_BG3}")
        line.append("   ")
        line.append(label, style=_TEXT)
        if hint:
            line.append(f"   {hint}", style=f"dim {_DIM}")
        console.print(line)

    console.rule(style=_BORDER)
    console.print()
    section("MERGE")
    item("1", "Merge sources → clean output",  "reads cards-merge/")
    item("2", "Merge and show diff",            "logs every change")
    item("3", "Dry run",                         "no files written")
    console.print()
    section("OUTPUT")
    item("4", "Open cards-clean/ in file manager")
    item("5", "Output file stats")
    console.print()
    section("SUPPORT")
    item("6", "Dependency check")
    item("7", "Help")
    console.print()
    quit_line = Text()
    quit_line.append(" q ", style=f"dim {_DIM} on {_BG3}")
    quit_line.append("   Quit", style=f"dim {_DIM}")
    console.print(quit_line)
    console.print()


def _deps_check() -> None:
    from importlib.metadata import PackageNotFoundError, version
    from rich.table import Table
    console.print()
    t = Table(show_header=True, header_style=f"dim {_DIM}", border_style=_BORDER,
              title=Text("DEPENDENCIES", style=f"bold {_TEXT}"), title_justify="left")
    t.add_column("Package", style=f"{_MID}")
    t.add_column("Version", style=f"bold {_TEXT}")
    t.add_column("Status")
    for pkg in ("typer", "rich", "vobject", "rapidfuzz", "phonenumbers"):
        try:
            t.add_row(pkg, version(pkg), Text("✓", style=f"bold {_GREEN}"))
        except PackageNotFoundError:
            t.add_row(pkg, "—", Text("MISSING", style=f"bold {_RED}"))
    console.print(t)


def _open_clean_dir() -> None:
    import os, platform
    clean_dir = Path("cards-clean").resolve()
    if not clean_dir.is_dir():
        console.print(Panel(Text("Run a merge first to create cards-clean/", style=_AMBER),
                            border_style=_AMBER, padding=(0, 1)))
        return
    system = platform.system()
    try:
        if system == "Darwin":   os.system(f'open "{clean_dir}"')
        elif system == "Linux":  os.system(f'xdg-open "{clean_dir}" 2>/dev/null &')
        elif system == "Windows": os.system(f'explorer "{clean_dir}"')
        console.print(Text(f"  ✓ Opened {clean_dir}", style=f"bold {_GREEN}"))
    except Exception as e:
        console.print(Text(f"  Could not open: {e}", style=_AMBER))


def _show_output_stats() -> None:
    import datetime
    from rich.table import Table
    clean_dir = Path("cards-clean")
    if not clean_dir.is_dir():
        console.print(Text("  cards-clean/ not found", style=f"dim {_DIM}"))
        return
    vcfs = sorted(clean_dir.glob("*.vcf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not vcfs:
        console.print(Text("  No output files yet", style=f"dim {_DIM}"))
        return
    console.print()
    t = Table(show_header=True, header_style=f"dim {_DIM}", border_style=_BORDER,
              title=Text("OUTPUT FILES", style=f"bold {_TEXT}"), title_justify="left")
    t.add_column("File",     style=f"bold {_TEXT}")
    t.add_column("Size",     style=f"{_MID}", justify="right")
    t.add_column("Modified", style=f"dim {_DIM}")
    for vcf in vcfs[:6]:
        s = vcf.stat()
        t.add_row(vcf.name, f"{s.st_size/1024:.1f} KB",
                  datetime.datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d  %H:%M"))
    console.print(t)


def _help() -> None:
    console.print()
    console.print(Panel(
        Text.from_markup(
            f"[bold {_TEXT}]Quick start[/]\n"
            f"  [dim {_DIM}]1.[/]  Drop exported .vcf files into  [bold {_ACCENT}]cards-merge/[/]\n"
            f"  [dim {_DIM}]2.[/]  Press  [bold {_ACCENT}]1[/]  to merge, normalise, and deduplicate\n"
            f"  [dim {_DIM}]3.[/]  Review uncategorised contacts when prompted\n"
            f"  [dim {_DIM}]4.[/]  Import the clean file from  [bold {_GREEN}]cards-clean/[/]  back into iCloud or Proton\n\n"
            f"[bold {_TEXT}]Exporting from your sources[/]\n"
            f"  [dim {_DIM}]iCloud :[/]  Settings → [your name] → iCloud → Contacts → Export vCard\n"
            f"  [dim {_DIM}]Proton :[/]  Contacts → ••• menu → Export\n\n"
            f"[bold {_TEXT}]Advanced CLI[/]\n"
            f"  [dim {_DIM}]vcard-normalize merge --help[/]"
        ),
        title=Text("HELP", style=f"dim {_DIM}"), title_align="left",
        border_style=_BORDER, padding=(1, 2),
    ))


def main() -> None:
    try:
        while True:
            console.clear()
            console.print()
            _wordmark()
            _status_bar()
            _menu()

            try:
                choice = console.input(Text.assemble(
                    Text("  Option", style=f"bold {_TEXT}"),
                    Text("  › ", style=f"bold {_ACCENT}"),
                )).strip().lower()
            except EOFError:
                break

            if choice in {"q", "quit", "exit"}:
                console.print(Text("\n  Bye.\n", style=f"dim {_DIM}"))
                break
            elif choice == "1":
                console.print(); _run("merge", "--yes")
            elif choice == "2":
                console.print(); _run("merge", "--yes", "--diff")
            elif choice == "3":
                console.print(); _run("merge", "--yes", "--dry-run")
            elif choice == "4":
                _open_clean_dir()
            elif choice == "5":
                _show_output_stats()
            elif choice == "6":
                _deps_check()
            elif choice == "7":
                _help()
            else:
                console.print(Text(f"  Unknown option: {choice!r}", style=f"dim {_RED}"))
                import time; time.sleep(0.6)
                continue

            console.print()
            console.input(Text("  Press Enter to return to menu… ", style=f"dim {_DIM}"))

    except KeyboardInterrupt:
        console.print(Text("\n  Bye.\n", style=f"dim {_DIM}"))


if __name__ == "__main__":
    main()
