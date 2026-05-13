"""
normalize.py
------------
Contest name and party normalization logic.

Keeping this in its own module makes it easy to unit test independently
of any database or file I/O.
"""

import re
import pandas as pd

# ---------------------------------------------------------------------------
# Contest name normalization
# ---------------------------------------------------------------------------

# Ordinal suffix → word-form mapping, generated for 1–99.
# Keys are lowercase (e.g. "13th"); values are their spelled-out equivalents
# (e.g. "thirteenth").  The regex below uses re.IGNORECASE so "13TH", "13th",
# and "13Th" all normalize identically — no manual entries needed for
# capitalisation variants.
#
# Coverage up to 99 handles every Illinois legislative and congressional
# district that currently exists.  If a district above 99 ever appears, extend
# _ORDINAL_CEILING.

_ORDINAL_CEILING = 99

_ONES = [
    "", "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
    "sixteenth", "seventeenth", "eighteenth", "nineteenth",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety",
]


def _ordinal_word(n: int) -> str:
    """Return the ordinal word for integer n (1–99)."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        # e.g. 20 → "twentieth", 30 → "thirtieth"
        base = _TENS[tens]
        if base.endswith("y"):
            return base[:-1] + "ieth"
        return base + "th"
    return f"{_TENS[tens]}-{_ONES[ones]}"


def _ordinal_suffix(n: int) -> str:
    """Return the numeric ordinal suffix for n (e.g. 1 → '1st', 13 → '13th')."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


ORDINAL_MAP: dict[str, str] = {
    _ordinal_suffix(n): _ordinal_word(n)
    for n in range(1, _ORDINAL_CEILING + 1)
}

_ORDINAL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ORDINAL_MAP) + r")\b",
    flags=re.IGNORECASE,
)


def normalize_contest_name(raw_name: str) -> str:
    """
    Normalize a contest name for consistent cross-year comparison.

    Transformations applied in order:
      1. Strip trailing parentheticals: "(Vote For 1)", "(To fill the vacancy...)"
         Must precede party-suffix stripping: a trailing parenthetical such as
         "(Fawell)" would otherwise hide the " - D" suffix from the regex.
      2. Strip party suffixes: " - D*", " - R*", " - G*", " - GP", etc.
      3. Strip trailing asterisks
      4. Strip "Unexpired N Year" phrases anywhere in the name
      5. Strip term-length suffixes: "Full 4 Year Term", "4 Year Term", etc.
      6. Uppercase
      7. Gender-neutral titles: committeeman/woman → committeeperson, etc.
      8. Spell out ordinal numerals: "81st" → "EIGHTY-FIRST"
         (plain integers like "District 1" are preserved)
    """
    name = raw_name.strip()

    # 1. Strip trailing parentheticals; repeat to handle multiple/nested ones
    for _ in range(3):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

    # 2. Strip party suffixes (D, R, G, GP) before uppercasing to catch mixed case
    name = re.sub(r"\s*-\s*(GP|[DRG])\*?\s*$", "", name, flags=re.IGNORECASE)

    # 3. Strip any remaining trailing asterisk
    name = re.sub(r"\s*\*\s*$", "", name).strip()

    # 4. Strip "Unexpired N Year" anywhere in the name
    #    e.g. "53 Trails Estates Unexpired 2 Year Park Commissioner" ->
    #         "53 Trails Estates Park Commissioner"
    name = re.sub(r"\s*unexpired\s+\d+\s+year\b", "", name, flags=re.IGNORECASE).strip()

    # 5. Strip term-length suffixes (with optional leading comma or dash)
    #    e.g. "District 1, 4 Year Term - R" -> "District 1"
    name = re.sub(
        r"[,]?\s*-?\s*Full\s+\d+\s+Year\s+Term\s*$", "", name, flags=re.IGNORECASE
    ).strip()
    name = re.sub(
        r"[,]?\s*-?\s*\d+\s+Year\s+Term\s*$", "", name, flags=re.IGNORECASE
    ).strip()

    # 6. Uppercase
    name = name.upper()

    # 7. Gender-neutral titles
    replacements = [
        (r"\bCOMMITTEEMAN\b", "COMMITTEEPERSON"),
        (r"\bCOMMITTEEWOMAN\b", "COMMITTEEPERSON"),
        (r"\bCONGRESSMAN\b", "CONGRESSPERSON"),
        (r"\bCONGRESSWOMAN\b", "CONGRESSPERSON"),
        (r"\bCHAIRMAN\b", "CHAIRPERSON"),
        (r"\bCHAIRWOMAN\b", "CHAIRPERSON"),
    ]
    for pattern, replacement in replacements:
        name = re.sub(pattern, replacement, name)

    # 8. Spell out ordinal numerals
    def _replace_ordinal(m: re.Match) -> str:
        return ORDINAL_MAP[m.group(0).lower()].upper()

    name = _ORDINAL_PATTERN.sub(_replace_ordinal, name)

    return name


# ---------------------------------------------------------------------------
# Party normalization
# ---------------------------------------------------------------------------

# CSVs use single-letter codes; Excel history uses full abbreviations.
PARTY_MAP: dict[str, str] = {
    "D": "DEM",
    "R": "REP",
    "DEM": "DEM",
    "REP": "REP",
    "GP": "GP",
    "WC": "WC",
}


def normalize_party(raw: str | float | None) -> str | None:
    """Normalize a raw party code to a canonical abbreviation, or None if blank."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    cleaned = str(raw).strip().upper()
    return PARTY_MAP.get(cleaned, cleaned)


# ---------------------------------------------------------------------------
# Candidate name corrections
# ---------------------------------------------------------------------------

# Keys are casefolded wrong names; values are the correct replacement.
# Casefolding keys at definition time means each lookup is a single O(1)
# dict access rather than a linear scan — important since this is called
# once per candidate row across thousands of records.
CANDIDATE_NAME_CORRECTIONS: dict[str, str] = {
    "jb pritzer": "JB PRITZKER",
}


def normalize_candidate_name(
    name: str,
    corrections: dict[str, str] = CANDIDATE_NAME_CORRECTIONS,
) -> str:
    """
    Apply known name corrections to a candidate's full name.

    ``corrections`` maps casefolded wrong names to their correct replacements.
    The corrected value is returned exactly as written in the dict value.

    Returns the original name unchanged if no correction applies.
    """
    return corrections.get(name.casefold(), name)
