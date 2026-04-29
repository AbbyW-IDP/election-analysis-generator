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

# Ordinal words that appear in contest names (add more as needed).
# Keys are lowercase; values are their spelled-out equivalents.
ORDINAL_MAP: dict[str, str] = {
    "1st": "first",
    "2nd": "second",
    "3rd": "third",
    "4th": "fourth",
    "5th": "fifth",
    "6th": "sixth",
    "7th": "seventh",
    "8th": "eighth",
    "9th": "ninth",
    "10th": "tenth",
    "11th": "eleventh",
    "12th": "twelfth",
    "21st": "twenty-first",
    "22nd": "twenty-second",
    "23rd": "twenty-third",
    "24th": "twenty-fourth",
    "39th": "thirty-ninth",
    "41st": "forty-first",
    "42nd": "forty-second",
    "45th": "forty-fifth",
    "48th": "forty-eighth",
    "49th": "forty-ninth",
    "50th": "fiftieth",
    "56th": "fifty-sixth",
    "65th": "sixty-fifth",
    "77th": "seventy-seventh",
    "81st": "eighty-first",
    "82nd": "eighty-second",
    "84th": "eighty-fourth",
    "85th": "eighty-fifth",
}

_ORDINAL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ORDINAL_MAP) + r")\b",
    flags=re.IGNORECASE,
)


def normalize_contest_name(raw_name: str) -> str:
    """
    Normalize a contest name for consistent cross-year comparison.

    Transformations applied in order:
      1. Strip party suffixes: " - D*", " - R*", " -D", " - R", etc.
      2. Strip trailing parentheticals: "(Vote For 1)", "(To fill the vacancy...)"
      3. Strip term-length suffixes: "Full 4 Year Term", "4 Year Term", etc.
      4. Uppercase
      5. Gender-neutral titles: committeeman/woman → committeeperson, etc.
      6. Spell out ordinal numerals: "81st" → "EIGHTY-FIRST"
         (plain integers like "District 1" are preserved)
    """
    name = raw_name.strip()

    # 1. Strip party suffixes (before uppercasing to catch mixed case)
    name = re.sub(r"\s*-\s*[DR]\*?\s*$", "", name, flags=re.IGNORECASE)

    # 2. Strip trailing parentheticals; repeat to handle multiple/nested ones
    for _ in range(3):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

    # 3. Strip term-length suffixes (with optional leading comma or dash)
    #    e.g. "District 1, 4 Year Term - R" -> "District 1"
    name = re.sub(
        r"[,]?\s*-?\s*Full\s+\d+\s+Year\s+Term\s*$", "", name, flags=re.IGNORECASE
    ).strip()
    name = re.sub(
        r"[,]?\s*-?\s*\d+\s+Year\s+Term\s*$", "", name, flags=re.IGNORECASE
    ).strip()

    # 4. Uppercase
    name = name.upper()

    # 5. Gender-neutral titles
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

    # 6. Spell out ordinal numerals
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


def normalize_party(raw: str | None) -> str | None:
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
