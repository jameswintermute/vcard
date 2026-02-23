from __future__ import annotations

import re
from typing import TYPE_CHECKING

import phonenumbers
from phonenumbers import NumberParseException
from rich.console import Console
from rich.prompt import Confirm, Prompt

from .model import Card

if TYPE_CHECKING:
    pass

console = Console()

# ── Phone formatting ───────────────────────────────────────────────────────────

def _format_spaced_e164(num: phonenumbers.PhoneNumber) -> str:
    """Format a parsed number as pretty international, e.g. +44 7980 220 220."""
    intl = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    out = intl.replace("-", " ").replace("(", "").replace(")", "")
    out = " ".join(out.split())

    # GB mobile tweak: +44 7xxx xxx xxx
    try:
        region = phonenumbers.region_code_for_number(num)
        nsn = phonenumbers.national_significant_number(num)
        if region == "GB" and len(nsn) == 10 and nsn.startswith("7"):
            return f"+44 {nsn[0:4]} {nsn[4:7]} {nsn[7:]}"
    except Exception:
        pass

    return out


def _infer_region_from_addresses(card: Card) -> str | None:
    name_map = {
        "United Kingdom": "GB", "UK": "GB", "Great Britain": "GB",
        "England": "GB", "Scotland": "GB", "Wales": "GB",
        "Northern Ireland": "GB", "United States": "US", "USA": "US",
        "Australia": "AU", "Canada": "CA", "Ireland": "IE",
        "France": "FR", "Germany": "DE", "Spain": "ES",
        "Italy": "IT", "Netherlands": "NL", "Sweden": "SE",
    }
    for adr in card.addresses:
        if not adr or not adr.country:
            continue
        c = adr.country.strip()
        if not c:
            continue
        if len(c) == 2 and c.isalpha():
            return c.upper()
        if c in name_map:
            return name_map[c]
    return None


def normalize_phones_in_cards(
    cards: list[Card],
    default_region: str = "GB",
    infer_from_adr: bool = True,
) -> None:
    """Normalise all phone numbers to E.164-style international format.

    Numbers that cannot be parsed or validated are left unchanged.
    Changes are logged on the card for the final report.
    """
    for card in cards:
        region = _infer_region_from_addresses(card) if infer_from_adr else None
        if not region:
            region = default_region

        new_tels: list[str] = []
        reformatted: list[str] = []

        for raw in card.tels:
            try:
                parsed = phonenumbers.parse(raw, region)
                if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
                    formatted = _format_spaced_e164(parsed)
                    new_tels.append(formatted)
                    if formatted != raw:
                        reformatted.append(f"{raw!r} → {formatted!r}")
                else:
                    new_tels.append(raw)
            except NumberParseException:
                new_tels.append(raw)

        card.tels = sorted(set(new_tels))
        if reformatted:
            card.log_change(f"Phone(s) reformatted: {'; '.join(reformatted)}")


# ── Address helpers ────────────────────────────────────────────────────────────

def ensure_country_in_addresses(cards: list[Card]) -> None:
    """Interactively prompt the user to fill in missing country on addresses."""
    for c in cards:
        if not c.addresses:
            continue
        missing = [a for a in c.addresses if not (a.country and a.country.strip())]
        if not missing:
            continue
        label = c.fn or c.org or "Unnamed"
        if Confirm.ask(f"[yellow]'{label}' has address(es) with no country. Set now?[/]"):
            country = Prompt.ask(
                "Enter country name (e.g., United Kingdom) or ISO-2 code (e.g., GB)",
                default="",
            )
            if country:
                for a in missing:
                    a.country = country
                c.log_change(f"Country set to '{country}' on {len(missing)} address(es)")


# ── KIND classification ────────────────────────────────────────────────────────

_ORG_TOKENS = (
    " ltd", " limited", " llc", " gmbh", " inc", " plc",
    " co.", " company", " s.r.o", " oy", " corp", " group",
    " associates", " & sons", " & co",
)


def classify_entities(cards: list[Card]) -> None:
    """Heuristically set KIND:individual or KIND:org when not already set."""
    for c in cards:
        if c.kind:
            continue
        name = (c.fn or "").lower()
        orgish = bool(
            (c.org and any(tok in c.org.lower() for tok in _ORG_TOKENS))
            or any(tok in name for tok in _ORG_TOKENS)
        )
        old = c.kind
        c.kind = "org" if orgish else "individual"
        if old != c.kind:
            c.log_change(f"KIND set to '{c.kind}'")


# ── Category auto-tagging ──────────────────────────────────────────────────────

# Default rules: (category_name, list_of_patterns_matched_against_fn/org/email/title)
# Patterns are plain substrings (case-insensitive) or regex strings starting with "re:"
_DEFAULT_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Work", [
        " ltd", " limited", " llc", " gmbh", " inc", " plc", " corp",
        " company", " group", " associates", "re:@(?!gmail|yahoo|hotmail|outlook|icloud|me\\.com|proton)",
    ]),
    ("Family", []),          # no auto-rule; left for interactive assignment
    ("Friends", []),         # no auto-rule
    ("School", ["school", "college", "university", "uni ", "academy", "edu"]),
    ("Medical", ["doctor", "dr.", "gp ", "clinic", "hospital", "pharmacy", "nhs", "health"]),
    ("Finance", ["bank", "insurance", "mortgage", "accountant", "finance", "tax"]),
    ("Government", ["council", "gov", "hmrc", "police", "fire service", "nhs"]),
]


def _matches_rule(card: Card, patterns: list[str]) -> bool:
    haystack = " ".join(filter(None, [
        card.fn, card.org, card.title,
        *(card.emails),
    ])).lower()
    for pat in patterns:
        if pat.startswith("re:"):
            if re.search(pat[3:], haystack, re.I):
                return True
        else:
            if pat in haystack:
                return True
    return False


def auto_tag_categories(
    cards: list[Card],
    rules: list[tuple[str, list[str]]] | None = None,
) -> None:
    """Apply rule-based category tags. Rules from config override defaults."""
    effective_rules = rules if rules is not None else _DEFAULT_CATEGORY_RULES
    for card in cards:
        added: list[str] = []
        for category, patterns in effective_rules:
            if not patterns:
                continue
            if category in card.categories:
                continue
            if _matches_rule(card, patterns):
                card.categories.append(category)
                added.append(category)
        if added:
            card.categories = sorted(set(card.categories))
            card.log_change(f"Auto-tagged categories: {', '.join(sorted(added))}")


def prompt_categories_interactive(cards: list[Card]) -> None:
    """Interactively review and assign categories for each card."""
    for c in cards:
        label = c.fn or c.org or "Unnamed"
        existing = f" [dim](already: {', '.join(c.categories)})[/]" if c.categories else ""
        if Confirm.ask(f"Assign/edit categories for [bold]{label}[/]{existing}?", default=False):
            cats = Prompt.ask(
                "Comma-separated categories (e.g., Family, Work, School)",
                default=", ".join(c.categories) if c.categories else "",
            )
            chosen = [s.strip() for s in cats.split(",") if s.strip()]
            before = set(c.categories)
            c.categories = sorted(set(chosen))
            added = set(c.categories) - before
            removed = before - set(c.categories)
            if added:
                c.log_change(f"Categories added interactively: {', '.join(sorted(added))}")
            if removed:
                c.log_change(f"Categories removed interactively: {', '.join(sorted(removed))}")

