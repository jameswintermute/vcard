"""
review.py — Interactive card-by-card review mode.

Presents each consolidated contact in a clean summary panel and lets the user:
  • Confirm the card as-is (press Enter / 'y')
  • Edit any field inline
  • Flag the card for deletion
  • Skip to the next card

Auto-clean pass runs first:
  - Phone numbers normalised to E.164 spaced format
  - Address fields title-cased where they look like raw ALL-CAPS or all-lower
  - Prompts for missing country / title / categories when detected

Progress is shown as  Card N / Total  so the user always knows where they are.
"""
from __future__ import annotations

import re
import unicodedata
from string import capwords

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .formatters import (
    classify_entities,
    normalize_phones_in_cards,
)
from .model import Address, Card

console = Console()

# ── helpers ──────────────────────────────────────────────────────────────────

_KNOWN_TITLES = [
    "Mr", "Mrs", "Ms", "Miss", "Dr", "Prof", "Rev", "Sir", "Lady",
    "Lord", "Capt", "Maj", "Col", "Gen", "Sgt", "Cpl", "Pte",
    "Eng", "Arch",
]

_COUNTRY_ALIASES: dict[str, str] = {
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "great britain": "United Kingdom",
    "us": "United States",
    "usa": "United States",
    "united states of america": "United States",
    "de": "Germany",
    "fr": "France",
    "ie": "Ireland",
    "es": "Spain",
    "it": "Italy",
    "nl": "Netherlands",
    "au": "Australia",
    "nz": "New Zealand",
    "ca": "Canada",
    "za": "South Africa",
    "in": "India",
    "cn": "China",
    "jp": "Japan",
}


def _normalise_country(raw: str) -> str:
    """Expand abbreviations / ISO codes to full country names."""
    key = raw.strip().lower()
    return _COUNTRY_ALIASES.get(key, raw.strip())


def _needs_title_case(s: str) -> bool:
    """Heuristic: string is all-caps or all-lowercase (ignoring digits/punct)."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters) or all(c.islower() for c in letters)


def _smart_title(s: str) -> str:
    """Title-case while preserving common acronyms."""
    return capwords(s)


def _autoclean_address(a: Address) -> Address:
    """Clean up address fields in place and return it."""
    fields = ["po_box", "extended", "street", "locality", "region", "postal_code", "country"]
    for f in fields:
        val = getattr(a, f)
        if not val:
            continue
        val = val.strip()
        if f == "country":
            val = _normalise_country(val)
        elif f == "postal_code":
            # Upper-case postcodes (UK style)
            val = val.upper()
        elif _needs_title_case(val):
            val = _smart_title(val)
        setattr(a, f, val or None)
    return a


def autoclean_cards(cards: list[Card], default_region: str = "GB") -> list[Card]:
    """
    Non-interactive auto-clean pass applied before review:
      1. Normalise phone numbers
      2. Title-case address fields that are all-caps / all-lower
      3. Expand country aliases
      4. Classify kind (individual / org)
    Returns the same list (mutated in-place).
    """
    normalize_phones_in_cards(cards, default_region=default_region, infer_from_adr=True)
    for card in cards:
        card.addresses = [_autoclean_address(a) for a in card.addresses]
    classify_entities(cards)
    return cards


# ── display helpers ───────────────────────────────────────────────────────────

def _address_str(a: Address) -> str:
    parts = [
        a.po_box, a.extended, a.street,
        a.locality, a.region, a.postal_code, a.country,
    ]
    return ", ".join(p for p in parts if p)


def _missing_hints(card: Card) -> list[str]:
    """Return a list of human-readable warnings for missing / suspect fields."""
    hints = []
    if not card.fn and not card.n:
        hints.append("⚠  No name (FN/N)")
    if not card.title:
        hints.append("ℹ  Title not set")
    if not card.categories:
        hints.append("ℹ  No categories")
    if card.addresses:
        for i, a in enumerate(card.addresses):
            if not a.country:
                hints.append(f"⚠  Address {i+1}: missing country")
    elif not card.emails and not card.tels:
        hints.append("⚠  No email, phone, or address")
    return hints


def _show_card(card: Card, index: int, total: int) -> None:
    """Pretty-print a single card summary."""
    label = card.fn or card.n or "(no name)"
    progress = f"[dim]Card {index} / {total}[/dim]"

    # Build detail lines
    lines: list[str] = []
    lines.append(f"[bold cyan]Name:[/]       {card.fn or ''}")
    if card.n and card.n != card.fn:
        lines.append(f"[bold cyan]N:[/]          {card.n}")
    lines.append(f"[bold cyan]Title:[/]      {card.title or '[dim](none)[/dim]'}")
    lines.append(f"[bold cyan]Org:[/]        {card.org or '[dim](none)[/dim]'}")
    lines.append(f"[bold cyan]Kind:[/]       {card.kind or '[dim](none)[/dim]'}")
    lines.append(f"[bold cyan]Birthday:[/]   {card.bday or '[dim](none)[/dim]'}")
    lines.append("")
    if card.emails:
        lines.append(f"[bold green]Email(s):[/]   {', '.join(card.emails)}")
    if card.tels:
        lines.append(f"[bold green]Phone(s):[/]   {', '.join(card.tels)}")
    if card.addresses:
        for i, a in enumerate(card.addresses, 1):
            lines.append(f"[bold green]Address {i}:[/]  {_address_str(a)}")
    if card.categories:
        lines.append(f"[bold green]Categories:[/] {', '.join(sorted(card.categories))}")

    hints = _missing_hints(card)
    if hints:
        lines.append("")
        for h in hints:
            lines.append(f"[yellow]{h}[/]")

    content = "\n".join(lines)
    console.print()
    console.print(Rule(f"{progress}  [bold]{label}[/bold]"))
    console.print(Panel(content, border_style="bright_blue", padding=(0, 2)))


# ── edit helpers ──────────────────────────────────────────────────────────────

def _edit_card(card: Card) -> None:
    """Let the user interactively edit fields of a card."""
    console.print("\n[bold]Edit card — leave blank to keep current value[/bold]")

    def _ask(label: str, current: str | None) -> str | None:
        hint = f"[dim]{current}[/dim]" if current else "[dim](empty)[/dim]"
        val = Prompt.ask(f"  {label} {hint}", default="").strip()
        return val if val else current

    card.fn = _ask("Full name (FN)", card.fn)
    card.title = _ask("Title (e.g. Dr, Mr, Ms)", card.title)
    card.org = _ask("Organisation", card.org)

    # Phones
    tels_str = ", ".join(card.tels)
    new_tels = _ask("Phone(s) — comma-separated", tels_str if tels_str else None)
    if new_tels:
        card.tels = [t.strip() for t in new_tels.split(",") if t.strip()]

    # Emails
    emails_str = ", ".join(card.emails)
    new_emails = _ask("Email(s) — comma-separated", emails_str if emails_str else None)
    if new_emails:
        card.emails = [e.strip().lower() for e in new_emails.split(",") if e.strip()]

    # Addresses
    if card.addresses:
        for i, a in enumerate(card.addresses, 1):
            console.print(f"\n  [cyan]Address {i}:[/] {_address_str(a)}")
            if Confirm.ask(f"  Edit address {i}?", default=False):
                a.street = _ask("    Street", a.street)
                a.locality = _ask("    City/Locality", a.locality)
                a.region = _ask("    Region/County", a.region)
                a.postal_code = _ask("    Postal code", a.postal_code)
                raw_country = _ask("    Country", a.country)
                if raw_country:
                    a.country = _normalise_country(raw_country)
    elif Confirm.ask("  No address on file — add one?", default=False):
        a = Address()
        a.street = Prompt.ask("  Street", default="").strip() or None
        a.locality = Prompt.ask("  City/Locality", default="").strip() or None
        a.region = Prompt.ask("  Region/County", default="").strip() or None
        a.postal_code = Prompt.ask("  Postal code", default="").strip() or None
        raw_country = Prompt.ask("  Country", default="").strip()
        a.country = _normalise_country(raw_country) if raw_country else None
        card.addresses.append(a)

    # Categories
    cats_str = ", ".join(sorted(card.categories))
    new_cats = _ask("Categories — comma-separated (e.g. Work, Family)", cats_str if cats_str else None)
    if new_cats:
        card.categories = sorted({c.strip() for c in new_cats.split(",") if c.strip()})

    # Kind
    console.print(f"\n  Current kind: [bold]{card.kind or '(none)'}[/bold]")
    kind_choice = Prompt.ask(
        "  Kind",
        choices=["individual", "org", "keep"],
        default="keep",
    )
    if kind_choice != "keep":
        card.kind = kind_choice

    console.print("[green]✓ Card updated[/green]")


# ── prompt helpers for missing fields ─────────────────────────────────────────

def _prompt_missing(card: Card) -> None:
    """After display, prompt user to fill in missing important fields."""
    hints = _missing_hints(card)
    if not hints:
        return

    has_missing_country = any("missing country" in h for h in hints)
    has_no_title = any("Title not set" in h for h in hints)
    has_no_cats = any("No categories" in h for h in hints)

    if has_missing_country:
        for a in card.addresses:
            if not a.country:
                raw = Prompt.ask(
                    f"  [yellow]Country missing for address '{_address_str(a)}'[/] — enter country (or blank to skip)",
                    default="",
                ).strip()
                if raw:
                    a.country = _normalise_country(raw)

    if has_no_title:
        console.print(f"  [dim]Known titles: {', '.join(_KNOWN_TITLES)}[/dim]")
        raw = Prompt.ask(
            "  [yellow]Title missing[/] — enter title (or blank to skip)",
            default="",
        ).strip()
        if raw:
            card.title = raw

    if has_no_cats:
        raw = Prompt.ask(
            "  [yellow]No categories[/] — enter categories (comma-separated, or blank to skip)",
            default="",
        ).strip()
        if raw:
            card.categories = sorted({c.strip() for c in raw.split(",") if c.strip()})


# ── main review loop ──────────────────────────────────────────────────────────

def review_cards(
    cards: list[Card],
    default_region: str = "GB",
    autoclean: bool = True,
    prompt_missing: bool = True,
) -> list[Card]:
    """
    Interactive card-by-card review loop.

    Parameters
    ----------
    cards:          The list of consolidated / merged cards to review.
    default_region: ISO2 region used as fallback for phone normalisation.
    autoclean:      Run auto-clean pass (phone fmt, address title-case, etc.) before review.
    prompt_missing: After displaying each card, ask about missing country/title/categories.

    Returns
    -------
    The (possibly edited) list of cards, with any flagged-for-deletion cards removed.
    """
    if autoclean:
        console.print("[cyan]Running auto-clean pass…[/cyan]")
        autoclean_cards(cards, default_region=default_region)
        console.print(f"[green]✓ Auto-clean complete ({len(cards)} cards)[/green]")

    # Sort: by FN then org
    cards = sorted(cards, key=lambda c: (c.fn or c.org or "zzz").lower())

    flagged_delete: set[int] = set()
    total = len(cards)
    i = 0

    console.print(f"\n[bold]Starting review of [cyan]{total}[/cyan] cards.[/bold]")
    console.print("[dim]Commands at each card:  Enter/y = accept • e = edit • d = delete • b = back • q = quit review[/dim]\n")

    while i < total:
        card = cards[i]
        _show_card(card, i + 1, total)

        deleted_marker = " [red][FLAGGED FOR DELETE][/red]" if i in flagged_delete else ""
        console.print(deleted_marker)

        if prompt_missing and i not in flagged_delete:
            _prompt_missing(card)

        action = Prompt.ask(
            "\n  [bold]Action[/bold] [dim](Enter=accept, e=edit, d=delete, b=back, q=quit)[/dim]",
            default="y",
        ).strip().lower()

        if action in {"y", "", "accept"}:
            i += 1
        elif action == "e":
            _edit_card(card)
            # Stay on same card so user can review the changes
        elif action == "d":
            if i in flagged_delete:
                flagged_delete.discard(i)
                console.print("[green]Delete flag removed[/green]")
            else:
                flagged_delete.add(i)
                console.print(f"[red]Card flagged for deletion[/red] (press 'd' again to un-flag)")
            i += 1
        elif action == "b":
            i = max(0, i - 1)
        elif action in {"q", "quit"}:
            console.print("[yellow]Quitting review early — cards reviewed so far will be kept.[/yellow]")
            break
        else:
            console.print("[red]Unknown command — try: Enter, e, d, b, q[/red]")

    kept = [c for j, c in enumerate(cards) if j not in flagged_delete]
    removed = len(flagged_delete)
    console.print(f"\n[green]Review complete.[/green] Kept [bold]{len(kept)}[/bold] cards"
                  + (f", removed [bold red]{removed}[/bold red]" if removed else "") + ".")
    return kept
