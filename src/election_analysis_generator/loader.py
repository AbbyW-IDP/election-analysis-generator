"""
loader.py
---------
ElectionLoader: reads election config and CSV source files, loads them
into an ElectionDatabase.

Elections are configured in elections.toml. Each entry maps a CSV filename
to an election name, year, dates, category, election_type, and turnout
figures. The loader reads the toml, checks which sources have not been
loaded yet, and loads any new ones.
"""

import re
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd

from src.election_analysis_generator.db import ElectionDatabase
from src.election_analysis_generator.models import Election

DEFAULT_SOURCES_DIR = Path("sources")
DEFAULT_CONFIG_PATH = Path("elections.toml")

VALID_CATEGORIES = frozenset(
    {"Consolidated", "Consolidated Primary", "General", "General Primary"}
)
VALID_ELECTION_TYPES = frozenset({"presidential", "midterm"})


# Required columns (post-normalisation names). All other source columns are optional.
REQUIRED_CSV_COLUMNS = frozenset({"contest_name_raw", "party", "total_votes"})

# All known optional columns. Any absent ones are added as NaN so the rest of
# the pipeline doesn't need to guard against missing columns.
OPTIONAL_CSV_COLUMNS = (
    "line_number",
    "choice_name",
    "percent_of_votes",
    "registered_voters",
    "ballots_cast",
    "num_precinct_total",
    "num_precinct_rptg",
    "over_votes",
    "under_votes",
)


def _normalize_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize CSV column names to internal conventions."""
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df.rename(
        columns={
            "contest_name": "contest_name_raw",
            "party_name": "party",
        }
    )


def _validate_csv_columns(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """
    Check that all required columns are present and add any missing optional
    columns as NaN.

    Raises ValueError naming every missing required column.
    """
    missing_required = REQUIRED_CSV_COLUMNS - set(df.columns)
    if missing_required:
        # Map back to original CSV header names for a readable error message
        display = {
            "contest_name_raw": "contest name",
            "party": "party",
            "total_votes": "total votes",
        }
        friendly = sorted(display.get(c, c) for c in missing_required)
        raise ValueError(
            f"{path.name} is missing required column(s): {', '.join(friendly)}"
        )

    # Add any absent optional columns as NaN so downstream code doesn't need
    # to guard against their absence
    for col in OPTIONAL_CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df


def _year_from_filename(filename: str) -> int | None:
    """
    Extract the election year from a filename.
    Tries the start of the stem first (handles date-suffixed names like
    2022-general-primary-2022-07-19.csv), then falls back to first 20xx match.
    """
    stem = Path(filename).stem
    match = re.match(r"(20\d{2})", stem)
    if match:
        return int(match.group(1))
    match = re.search(r"(20\d{2})", stem)
    return int(match.group(1)) if match else None


def _validate_config_entry(entry: dict, key: str) -> None:
    """Raise ValueError if a config entry has invalid category or election_type."""
    category = entry.get("category")
    election_type = entry.get("election_type")

    if category is not None and category not in VALID_CATEGORIES:
        raise ValueError(
            f"[elections.{key}] Invalid category {category!r}. "
            f"Must be one of: {sorted(VALID_CATEGORIES)}"
        )
    if election_type is not None and election_type not in VALID_ELECTION_TYPES:
        raise ValueError(
            f"[elections.{key}] Invalid election_type {election_type!r}. "
            f"Must be one of: {sorted(VALID_ELECTION_TYPES)}"
        )


def load_elections_config(config_path: Path = DEFAULT_CONFIG_PATH) -> list[dict]:
    """
    Read elections.toml and return a list of election config dicts.

    Each entry must have: name, source_file
    Optional: year (inferred from filename if absent),
              election_date, results_last_updated,
              category, election_type,
              ballots_cast, registered_voters

    Raises ValueError if any entry has an invalid category or election_type.
    """
    if not config_path.exists():
        return []
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    entries = []
    for key, cfg in raw.get("elections", {}).items():
        _validate_config_entry(cfg, key)
        entries.append(cfg)
    return entries


class ElectionLoader:
    """
    Reads election source files and loads them into an ElectionDatabase.

    Elections are defined in elections.toml. Call sync() to load any
    elections defined in the config that haven't been loaded yet.

    Usage:
        loader = ElectionLoader(db)
        loader.sync(sources_dir=Path("sources"), config_path=Path("elections.toml"))
    """

    def __init__(self, db: ElectionDatabase) -> None:
        self._db = db

    def sync(
        self,
        sources_dir: Path = DEFAULT_SOURCES_DIR,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> dict[str, tuple[Election, list[str]]]:
        """
        Scan elections.toml for elections whose source files haven't been
        loaded yet and load them.

        Returns:
            Dict mapping source filename -> (Election, new_unrecognized_contest_names)
            for each newly loaded file.
        """
        if not sources_dir.exists():
            raise FileNotFoundError(f"Sources directory not found: {sources_dir}")

        configs = load_elections_config(config_path)
        if not configs:
            print(f"  No elections found in {config_path}")
            return {}

        results = {}
        for entry in configs:
            filename = entry["source_file"]
            if self._db.is_source_loaded(filename):
                continue

            # Election may already exist under this name. Register the CSV as a
            # known source so future syncs skip it, but don't re-insert.
            existing = self._db.get_election_by_name(entry["name"])
            if existing is not None:
                self._db.register_source(filename, existing.id)
                continue

            path = sources_dir / filename
            if not path.exists():
                print(f"  Skipping {filename}: file not found in {sources_dir}")
                continue

            election, new_names = self.load_csv(path, entry)
            results[filename] = (election, new_names)

        return results

    def load_csv(
        self,
        path: Path,
        config: dict,
    ) -> tuple[Election, list[str]]:
        """
        Load a single election CSV into the database.

        Args:
            path:   Path to the CSV file.
            config: Dict from elections.toml with at minimum 'name' and 'source_file'.

        Returns:
            (Election, new_unrecognized_contest_names)
        """
        try:
            df = pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="windows-1252")
        df = _normalize_csv_columns(df)
        df = _validate_csv_columns(df, path)

        year = config.get("year") or _year_from_filename(path.name)
        if year is None:
            raise ValueError(
                f"Could not determine year for {path.name}. Add 'year' to elections.toml."
            )

        election = Election(
            id=None,
            name=config["name"],
            year=year,
            election_date=date.fromisoformat(config["election_date"])
            if config.get("election_date")
            else None,
            results_last_updated=date.fromisoformat(config["results_last_updated"])
            if config.get("results_last_updated")
            else None,
            source_file=path.name,
            category=config.get("category", ""),
            election_type=config.get("election_type", ""),
            ballots_cast=config.get("ballots_cast"),
            registered_voters=config.get("registered_voters"),
        )

        # insert_election now returns (election, new_names) directly —
        # no need to diff the contest_names registry before and after.
        election, new_names = self._db.insert_election(election, df)

        self._db.register_source(path.name, election.id)
        return election, new_names
