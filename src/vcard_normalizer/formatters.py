from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException
from rich.console import Console
from rich.prompt import Confirm, Prompt

from .model import Card

console = Console()



def _format_spaced_e164(num: phonenumbers.PhoneNumber) -> str:
    # Base international formatting first
    intl = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    out = intl.replace("-", " ").replace("(", "").replace(")", "")
    out = " ".join(out.split())  # collapse multiple spaces

    # GB tweak: show mobiles as +44 7xxx xxx xxx (e.g., +44 7980 220 220)
    try:
        region = phonenumbers.region_code_for_number(num)
        nsn = phonenumbers.national_significant_number(num)
        if region == "GB" and len(nsn) == 10 and nsn.startswith("7"):
            # +44 <4> <3> <3>
            return f"+44 {nsn[0:4]} {nsn[4:7]} {nsn[7:]}"
    except Exception:
        pass

    return out


def _infer_region_from_addresses(card: Card) -> str | None:
    # Try mapping country names to ISO2 region codes for common cases
    name_map = {
        "United Kingdom": "GB",
        "UK": "GB",
        "Great Britain": "GB",
        "England": "GB",
        "Scotland": "GB",
        "Wales": "GB",
        "Northern Ireland": "GB",
        "United States": "US",
        "USA": "US",
    }
    for adr in card.addresses:
        if not adr or not adr.country:
            continue
        c = adr.country.strip()
        if not c:
            continue
        # If already ISO2 like "GB" or "US"
        if len(c) == 2 and c.isalpha():
            return c.upper()
        # Try name mapping
        if c in name_map:
            return name_map[c]
    return None


def normalize_phones_in_cards(cards: list[Card], default_region: str = "GB", infer_from_adr: bool = True) -> None:
    for card in cards:
        region = _infer_region_from_addresses(card) if infer_from_adr else None
        if not region:
            region = default_region
        new_tels: list[str] = []
        for raw in card.tels:
            try:
                parsed = phonenumbers.parse(raw, region)
                if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
                    new_tels.append(_format_spaced_e164(parsed))
                else:
                    new_tels.append(raw)
            except NumberParseException:
                new_tels.append(raw)
        card.tels = sorted(set(new_tels))


def ensure_country_in_addresses(cards: list[Card]) -> None:
    for c in cards:
        missing_any = any(not (a and a.country and a.country.strip()) for a in c.addresses) or (not c.addresses)
        if not missing_any:
            continue
        label = c.fn or c.org or "Unnamed"
        if Confirm.ask(f"[yellow]Contact '{label}' has address(es) missing a country. Set country now?[/]"):
            country = Prompt.ask("Enter country name (e.g., United Kingdom) or ISO2 code (e.g., GB)", default="")
            if not country:
                continue
            if not c.addresses:
                # create a minimal address container if none exist
                from .model import Address
                c.addresses.append(Address(country=country))
            else:
                for a in c.addresses:
                    if not a.country:
                        a.country = country


def classify_entities(cards: list[Card]) -> None:
    orgish_tokens = (" ltd", " limited", " llc", " gmbh", " inc", " plc", " co.", " company", " s.r.o", " oy")
    for c in cards:
        if c.kind:
            continue
        name = (c.fn or "").lower()
        orgish = False
        if c.org and (not c.fn or any(tok in c.org.lower() for tok in orgish_tokens)):
            orgish = True
        elif any(tok in name for tok in orgish_tokens):
            orgish = True
        c.kind = "org" if orgish else "individual"


def prompt_categories_interactive(cards: list[Card]) -> None:
    for c in cards:
        label = c.fn or c.org or "Unnamed"
        if Confirm.ask(f"Assign categories to [bold]{label}[/]?"):
            cats = Prompt.ask("Enter comma-separated categories (e.g., Family, Work, School)", default="")
            if not cats:
                continue
            chosen = [s.strip() for s in cats.split(",") if s.strip()]
            c.categories = sorted(set(c.categories) | set(chosen))
