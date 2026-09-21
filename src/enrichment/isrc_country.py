"""ISRC registrant prefix -> country, plus a WEAK country -> language hint.

The first two characters of an ISRC identify the *registering agency's* territory, not the artist's
nationality or the song's language. Treat everything here as a weak signal: never use it alone for rules.
"""

from __future__ import annotations

# Prefix -> ISO 3166-1 alpha-2. Only prefixes we are confident about; unknown -> None.
# Most prefixes are the ISO code itself; a few are special agency allocations.
_SPECIAL: dict[str, str] = {
    "QM": "US",  # US allocation (widely used by digital-era US labels)
    "QZ": "US",  # US allocation
    "UK": "GB",  # historical UK allocation (ISO code for UK is GB)
    "GX": "GB",  # extra UK allocation
    "FX": "FR",  # extra France allocation
}

_ISO_CODES: tuple[str, ...] = (
    "US", "GB", "FR", "DE", "IT", "ES", "PT", "SE", "NO", "DK", "FI", "IS", "NL", "BE", "LU", "AT", "CH",
    "IE", "PL", "CZ", "SK", "HU", "RO", "BG", "GR", "TR", "HR", "RS", "SI", "LT", "LV", "EE", "UA", "RU",
    "JP", "KR", "CN", "TW", "HK", "IN", "PK", "BD", "LK", "NP", "TH", "VN", "ID", "MY", "SG", "PH",
    "AU", "NZ", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "UY", "PR", "DO", "JM", "CU",
    "ZA", "NG", "EG", "IL", "SA", "AE",
)

ISRC_PREFIX_COUNTRY: dict[str, str] = {**{c: c for c in _ISO_CODES}, **_SPECIAL}

# WEAK: only for countries where one language dominates recorded music. IN is deliberately absent
# (Hindi, Tamil, Malayalam, ... all share it), as are US/GB/CA/AU (English is the default anyway and
# says little about a specific song).
_COUNTRY_LANGUAGE: dict[str, str] = {
    "JP": "japanese", "KR": "korean", "FR": "french", "DE": "german", "ES": "spanish", "IT": "italian",
    "BR": "portuguese", "PT": "portuguese", "RU": "russian", "PL": "polish", "TR": "turkish",
    "GR": "greek", "SE": "swedish", "NO": "norwegian", "DK": "danish", "FI": "finnish",
    "NL": "dutch", "CN": "chinese", "TW": "chinese", "TH": "thai", "VN": "vietnamese",
    "ID": "indonesian", "UA": "ukrainian", "IL": "hebrew", "MX": "spanish", "AR": "spanish",
    "CL": "spanish", "CO": "spanish",
}


def isrc_country(isrc: str | None) -> str | None:
    """ISO 3166-1 alpha-2 country for an ISRC's prefix, or None if invalid/unknown.

    Case-insensitive; hyphens and spaces are stripped; must be 12 ASCII alphanumerics afterwards.
    """
    if not isinstance(isrc, str):
        return None
    code = isrc.replace("-", "").replace(" ", "").upper()
    if len(code) != 12 or not (code.isascii() and code.isalnum()):
        return None
    if not code[:2].isalpha():
        return None
    return ISRC_PREFIX_COUNTRY.get(code[:2])


def language_hint_from_country(country: str | None) -> str | None:
    """WEAK language guess (canonical name) for a mostly mono-lingual country; never use alone for rules."""
    if not isinstance(country, str):
        return None
    return _COUNTRY_LANGUAGE.get(country.strip().upper())
