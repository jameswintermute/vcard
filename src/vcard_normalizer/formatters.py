from __future__ import annotations

import re
from typing import TYPE_CHECKING

import phonenumbers
from phonenumbers import NumberParseException
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.text import Text

from .model import Card

if TYPE_CHECKING:
    pass

console = Console()

# ── Phone formatting ───────────────────────────────────────────────────────────

def _format_spaced_e164(num: phonenumbers.PhoneNumber) -> str:
    intl = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    out = intl.replace("-", " ").replace("(", "").replace(")", "")
    out = " ".join(out.split())
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
    for c in cards:
        if not c.addresses:
            continue
        missing = [a for a in c.addresses if not (a.country and a.country.strip())]
        if not missing:
            continue
        label = c.fn or c.org or "Unnamed"
        if Confirm.ask(f"[yellow]'{label}' has address(es) with no country. Set now?[/]"):
            country = Prompt.ask(
                "Enter country name or ISO-2 code",
                default="",
            )
            if country:
                for a in missing:
                    a.country = country
                c.log_change(f"Country set to '{country}' on {len(missing)} address(es)")


# ── KIND classification ────────────────────────────────────────────────────────
#
# We only set KIND when we're genuinely confident:
#   - "org"        → name/org contains a strong legal entity token (Ltd, plc, etc.)
#   - "individual" → contact has a real name AND phone number (strong signal it's a person)
#   - unset        → everything else (email-only contacts, ambiguous names, etc.)
#
# Contacts that remain unset are surfaced in the post-processing review prompt.

_ORG_TOKENS = (
    " ltd", " limited", " llc", " gmbh", " inc", " plc",
    " co.", " company", " s.r.o", " oy", " corp", " group",
    " associates", " & sons", " & co",
)

_BUSINESS_SECOND_WORDS = {
    "mechanics", "taxi", "services", "direct", "garage", "dental", "clinic",
    "centre", "center", "school", "college", "group", "solutions", "systems",
    "consulting", "consultants", "hotel", "bar", "restaurant", "cafe", "shop",
    "store", "fitness", "gym", "academy", "training", "logistics", "transport",
    "byfleet", "weybridge", "team", "support", "care", "health", "management",
    "property", "estate", "estates", "law", "legal", "finance", "financial",
    "media", "digital", "technology", "tech", "engineering",
}

# Strict "FirstName LastName" — allows McX, O'X style names
_PERSONAL_NAME_RE = re.compile(r"^[A-Z][a-z]{1,20} [A-Z][a-zA-Z']{1,20}$", re.UNICODE)


def _is_email_only(card: Card) -> bool:
    """True if the contact has no real name/org/phone — just an email address."""
    has_real_name = bool(card.fn and "@" not in card.fn and len(card.fn) > 3)
    has_org = bool(card.org)
    has_phone = bool(card.tels)
    return not (has_real_name or has_org or has_phone)


def _looks_like_person(fn: str) -> bool:
    """True only if FN looks like a genuine personal name."""
    if not _PERSONAL_NAME_RE.match(fn):
        return False
    words = fn.lower().split()
    if len(words) != 2:
        return False
    return not (words[1] in _BUSINESS_SECOND_WORDS or words[0] in _BUSINESS_SECOND_WORDS)


def classify_entities(cards: list[Card]) -> None:
    """Conservatively set KIND only when genuinely confident.

    - org        : name/org contains a strong legal entity token (Ltd, plc, etc.)
    - individual : exactly "FirstName LastName" pattern AND has a phone number
    - unset      : everything else — surfaced in the post-processing review prompt
    """
    for c in cards:
        if c.kind:
            continue
        if _is_email_only(c):
            continue
        name = (c.fn or "").lower()
        org_name = (c.org or "").lower()
        is_org = (
            any(tok in org_name for tok in _ORG_TOKENS)
            or any(tok in name for tok in _ORG_TOKENS)
        )
        if is_org:
            c.kind = "org"
            c.log_change("KIND set to 'org'")
            continue
        if _looks_like_person(c.fn or "") and c.tels:
            c.kind = "individual"
            c.log_change("KIND set to 'individual'")


# ── Category auto-tagging ──────────────────────────────────────────────────────
#
# The Work rule no longer fires on email domain alone.
# A non-consumer domain email is weak evidence — "contractend@minifs.co.uk" is
# a transactional address, not a work contact.
#
# Work now requires a corporate token in the name/org OR title field.
# The email domain regex is removed from defaults; it can be re-enabled in
# local/vcard.conf by the user if they want more aggressive tagging.

_DEFAULT_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Work", [
        " ltd", " limited", " llc", " gmbh", " inc", " plc", " corp",
        " company", " group", " associates",
        # NOTE: no email domain regex here — too many false positives
    ]),
    ("Family", []),       # no auto-rule; left for interactive assignment
    ("Friends", []),      # no auto-rule
    ("School", ["school", "college", "university", "uni ", "academy", ".edu"]),
    ("Medical", ["doctor", "dr.", "gp ", "clinic", "hospital", "pharmacy", "nhs", "health"]),
    ("Finance", ["bank", "insurance", "mortgage", "accountant", "finance", "tax"]),
    ("Government", ["council", ".gov.uk", "hmrc", "police", "fire service", "mod.gov"]),
]


def _matches_rule(card: Card, patterns: list[str]) -> bool:
    # Only match against name fields and title — NOT email addresses
    # This prevents transactional email contacts being auto-tagged
    haystack = " ".join(filter(None, [card.fn, card.org, card.title])).lower()
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
    """Apply rule-based category tags. Email-only contacts are skipped."""
    effective_rules = rules if rules is not None else _DEFAULT_CATEGORY_RULES
    for card in cards:
        # Don't auto-tag email-only contacts — we'd just be guessing
        if _is_email_only(card):
            continue
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


# ── Post-processing review prompt ──────────────────────────────────────────────

_FALLBACK_CATEGORIES = ["Family", "Friends", "Work", "School", "Medical", "Finance", "Government", "Other"]

# Sentinel value placed on a card's categories to mark it for deletion
_DELETE_SENTINEL = "__DELETE__"


def _collect_existing_categories(cards: list[Card]) -> list[str]:
    """Return all unique categories already present across all cards, sorted."""
    seen: set[str] = set()
    for c in cards:
        for cat in c.categories:
            if cat and cat != _DELETE_SENTINEL:
                seen.add(cat)
    # Lexicographic, case-insensitive (Army < Finance, not army > Finance)
    user_cats = sorted(seen, key=str.casefold)
    if not user_cats:
        return list(_FALLBACK_CATEGORIES)
    # Append any standard fallback categories not already present
    extras = [c for c in _FALLBACK_CATEGORIES if c not in seen]
    return user_cats + extras


def _render_cat_grid(cats: list[str], cols: int = 4) -> None:
    """Print the category grid column-major with styled cells."""
    import math
    n    = len(cats)
    rows = math.ceil(n / cols)
    max_cat = max((len(c) for c in cats), default=8)
    col_w   = max_cat + 5

    _ACCENT = "#4d9fff"
    _DIM    = "#546075"
    _MID    = "#8896af"
    _BG3    = "#1c2230"

    for r in range(rows):
        row_text = Text("  ")
        for col in range(cols):
            idx = col * rows + r
            if idx >= n:
                break
            cat  = cats[idx]
            num  = str(idx + 1)
            cell = Text()
            cell.append(f"{num:>2}", style=f"dim {_DIM}")
            cell.append(f" {cat}", style=f"{_MID}")
            # pad to col_w (visual chars only)
            pad = col_w - len(num) - 1 - len(cat)
            cell.append(" " * max(pad, 2))
            row_text.append_text(cell)
        console.print(row_text)

    # Action pills row
    console.print()
    pills = Text("  ")
    def pill(key: str, label: str, danger: bool = False) -> None:
        colour = "#f05c5c" if danger else _ACCENT
        pills.append(f" {key} ", style=f"bold black on {colour}")
        pills.append(f" {label}   ", style=f"dim {_DIM}")
    pill("Enter", "confirm")
    pill("Space", "skip")
    pill("c",     "custom tag")
    pill("d",     "delete", danger=True)
    pill("q",     "stop")
    console.print(pills)


def _progress_bar(done: int, total: int, width: int = 24) -> Text:
    _ACCENT = "#4d9fff"
    _BG3    = "#1c2230"
    _DIM    = "#546075"
    filled = round(width * done / total) if total else 0
    bar = Text()
    bar.append("█" * filled,           style=_ACCENT)
    bar.append("░" * (width - filled), style=f"dim {_BG3}")
    bar.append(f"  {done} / {total}",  style=f"dim {_DIM}")
    return bar


def prompt_review_uncategorised(cards: list[Card]) -> None:
    """Category review — styled to match the mockup design."""
    uncategorised = [c for c in cards if not c.categories]
    if not uncategorised:
        return

    _ACCENT  = "#4d9fff"
    _GREEN   = "#3ecf8e"
    _RED     = "#f05c5c"
    _AMBER   = "#f0a500"
    _TEXT    = "#c9d1e0"
    _MID     = "#8896af"
    _DIM     = "#546075"
    _BORDER  = "#2a3347"

    console.print()
    header = Text()
    header.append(f"  {len(uncategorised)}", style=f"bold {_AMBER}")
    header.append(" contact(s) have no category assigned.", style=f"{_MID}")
    console.print(header)

    if not Confirm.ask(Text("  Review and categorise now?", style=f"bold {_TEXT}"), default=False):
        console.print(Text("  Skipped.", style=f"dim {_DIM}"))
        return

    category_list = _collect_existing_categories(cards)
    total = len(uncategorised)

    def _resolve_token(token: str, cats: list[str]) -> str | None:
        t = token.strip()
        if not t:
            return None
        if t.isdigit():
            n = int(t)
            return cats[n - 1] if 1 <= n <= len(cats) else None
        lc = t.lower()
        exact = [cat for cat in cats if cat.lower() == lc]
        if exact:
            return exact[0]
        matches = [cat for cat in cats if cat.lower().startswith(lc)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            console.print(Text(f"  Ambiguous: {matches} — type more characters.", style=f"dim {_AMBER}"))
        return None

    for idx, c in enumerate(uncategorised, 1):
        console.print()
        console.rule(style=_BORDER)
        console.print()

        # Progress bar
        console.print(Text("  UNCATEGORISED CONTACTS  ") + _progress_bar(idx - 1, total))
        console.print()

        # Contact header
        label = c.fn or c.org or "Unnamed"
        if len(label) > 55:
            label = label[:52] + "…"

        name_line = Text()
        name_line.append(f"  {label}", style=f"bold {_TEXT}")
        if c._source_files:
            srcs = " · ".join(s.replace("protonContacts", "proton").replace("-2026-02-23", "")
                              for s in c._source_files)
            name_line.append(f"   {srcs}", style=f"dim {_DIM}")
        console.print(name_line)

        detail_parts = []
        if c.emails:  detail_parts.append(c.emails[0])
        if c.tels:    detail_parts.append(c.tels[0])
        if c.org and c.org != label: detail_parts.append(c.org[:40])
        if detail_parts:
            detail = Text("  " + "   ·   ".join(detail_parts), style=f"dim {_MID}")
            console.print(detail)

        console.print()
        _render_cat_grid(category_list)
        console.print()

        raw = Prompt.ask(
            Text.assemble(
                Text("  › ", style=f"bold {_ACCENT}"),
            ),
            default=""
        ).strip()

        if raw.lower() == "q":
            console.print(Text("  Stopped.", style=f"dim {_DIM}"))
            break
        if not raw or raw == " ":
            continue
        if raw.lower() == "d":
            c.categories = [_DELETE_SENTINEL]
            c.log_change("Marked for deletion during review")
            console.print(Text("  ✗  Marked for deletion", style=f"bold {_RED}"))
            continue

        chosen_cats: list[str] = []
        deleted = False
        for token in raw.split(","):
            token = token.strip().lower()
            if token == "d":
                deleted = True
                break
            elif token == "c":
                custom = Prompt.ask(Text("  Custom category", style=f"{_MID}")).strip()
                if custom:
                    chosen_cats.append(custom)
                    if custom not in category_list:
                        category_list.insert(
                            next((i for i, x in enumerate(category_list)
                                  if x.lower() > custom.lower()), len(category_list)),
                            custom,
                        )
            else:
                resolved = _resolve_token(token, category_list)
                if resolved:
                    chosen_cats.append(resolved)

        if deleted:
            c.categories = [_DELETE_SENTINEL]
            c.log_change("Marked for deletion during review")
            console.print(Text("  ✗  Marked for deletion", style=f"bold {_RED}"))
        elif chosen_cats:
            before = set(c.categories)
            c.categories = sorted(set(c.categories) | set(chosen_cats))
            added = set(c.categories) - before
            if added:
                c.log_change(f"Categories assigned in review: {', '.join(sorted(added))}")
            result = Text()
            result.append("  ✓  Tagged: ", style=f"bold {_GREEN}")
            result.append(", ".join(sorted(chosen_cats)), style=f"{_TEXT}")
            console.print(result)

    console.print()
    console.rule(style=_BORDER)
    console.print()


def prompt_categories_interactive(cards: list[Card]) -> None:
    """Legacy interactive review: ask about every card (used in full --interactive mode)."""
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
