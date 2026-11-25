"""
Country name → ISO 3166-1 alpha-2 code (lower case, as Apple's X-ABADR uses).

The visible country *name* is the source of truth. The Apple country code
(X-ABADR) is derived from it at export time, so a stale stored code can never
override a name the user has corrected.

Names come from libphonenumber's region display names (English) when the
optional `phonenumbers` package is available, plus common aliases. Unknown
names return "" so callers can omit the code and let the device infer it.
"""
from __future__ import annotations

import re
from functools import lru_cache

_ALIASES = {
    "uk": "gb", "u.k.": "gb", "great britain": "gb", "britain": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb", "united kingdom": "gb",
    "united kingdom of great britain and northern ireland": "gb",
    "us": "us", "u.s.": "us", "usa": "us", "u.s.a.": "us", "united states": "us",
    "united states of america": "us", "america": "us",
    "australia": "au", "canada": "ca", "ireland": "ie", "republic of ireland": "ie",
    "new zealand": "nz", "poland": "pl", "germany": "de", "france": "fr", "spain": "es",
    "italy": "it", "netherlands": "nl", "nederland": "nl", "the netherlands": "nl",
    "belgium": "be", "switzerland": "ch", "sweden": "se", "norway": "no", "denmark": "dk",
    "portugal": "pt", "south africa": "za", "india": "in", "japan": "jp", "singapore": "sg",
    "hong kong": "hk", "guernsey": "gg", "jersey": "je", "isle of man": "im",
}


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        import phonenumbers
        from phonenumbers.geocoder import _region_display_name  # private but stable since 8.x
        for region in phonenumbers.SUPPORTED_REGIONS:
            name = _region_display_name(region, "en")
            if name:
                table[_key(name)] = region.lower()
    except Exception:
        pass
    table.update(_ALIASES)
    return table


def country_code_for(name: str | None) -> str:
    """Return the lower-case ISO alpha-2 code for a country name, or ""."""
    k = _key(name or "")
    if not k:
        return ""
    if len(k) == 2 and k.isalpha():
        return k
    return _names().get(k, "")


def effective_apple_code(country: str | None, stored_code: str | None) -> str:
    """Code to write as X-ABADR: derived from the visible country name.

    * name maps to a code  → that code (a stale stored code is ignored)
    * no country name      → the stored code (nothing to contradict it)
    * unrecognised name    → "" (omit; the device infers from the text)
    """
    derived = country_code_for(country)
    if derived:
        return derived
    if not (country or "").strip():
        return (stored_code or "").strip().lower()
    return ""
