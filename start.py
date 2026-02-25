#!/usr/bin/env python3
"""vcard — Address Book Cleaner.  Run with:  python3 start.py"""
import sys
import os
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir    = os.path.join(script_dir, "src")

sys.path.insert(0, src_dir)
os.environ["PYTHONPATH"] = src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")
os.chdir(script_dir)

# ── First-run detection ───────────────────────────────────────────────────────
# Show a welcome message if cards-merge/ is empty and cards-clean/ doesn't exist
def _first_run() -> bool:
    merge_dir = Path(script_dir) / "cards-merge"
    clean_dir = Path(script_dir) / "cards-clean"
    if not merge_dir.is_dir():
        return True
    vcfs = list(merge_dir.glob("*.vcf"))
    return len(vcfs) == 0 and not any(clean_dir.glob("*.vcf")) if clean_dir.is_dir() else len(vcfs) == 0

def _welcome() -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold #4d9fff]Welcome to vcard[/] — Address Book Cleaner\n\n"
            "There are just [bold]two folders[/] you need to know about:\n\n"
            "  [bold #4d9fff]cards-merge/[/]   Drop your exported contact files here\n"
            "  [dim]           Export from iCloud: Settings → [your name] → iCloud → Contacts → Export vCard[/]\n"
            "  [dim]           Export from Proton: Contacts → ••• → Export[/]\n\n"
            "  [bold #3ecf8e]cards-clean/[/]   Your cleaned, merged output appears here\n"
            "  [dim]           Import this file back into iCloud or Proton when done[/]\n\n"
            "Everything else in this folder is program code — you can ignore it.\n\n"
            "[dim]When you're ready, choose option [bold]1[/] from the menu to run your first merge.[/]"
        ),
        title=Text("  Getting Started  ", style="dim #546075"),
        title_align="left",
        border_style="#2a3347",
        padding=(1, 2),
    ))
    console.print()
    console.input("[dim #546075]  Press Enter to continue…[/dim #546075]")

if _first_run():
    _welcome()

from vcard_normalizer.launcher import main
main()
