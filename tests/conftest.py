"""
conftest.py
-----------
Shared pytest fixtures for the election_analysis test suite.
"""

from datetime import date

import pandas as pd
import pytest

from src.election_analysis_generator.db import ElectionDatabase
from src.election_analysis_generator.models import Election


@pytest.fixture
def db():
    """In-memory ElectionDatabase, isolated per test."""
    database = ElectionDatabase(db_path=":memory:")
    yield database
    database.close()


@pytest.fixture
def sample_election():
    """A minimal Election object for use in tests."""
    return Election(
        id=None,
        name="2022 General Primary",
        year=2022,
        election_date=date(2022, 6, 28),
        results_last_updated=date(2022, 7, 19),
        summary_file="2022-general-primary.csv",
        category="General Primary",
        election_type="midterm",
    )


def make_candidates_df(rows: list[dict]) -> pd.DataFrame:
    """
    Build a minimal candidates DataFrame suitable for insert_election().
    Any omitted fields default to sensible values.
    """
    defaults = {
        "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
        "line_number": 1,
        "choice_name": "Jane Smith",
        "party": "DEM",
        "total_votes": 1000.0,
        "percent_of_votes": 100.0,
        "registered_voters": 10000.0,
        "ballots_cast": 5000.0,
        "num_precinct_total": 10.0,
        "num_precinct_rptg": 10.0,
        "over_votes": 0.0,
        "under_votes": 0.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def seed_election(
    db: ElectionDatabase,
    name: str,
    year: int,
    rows: list[dict],
    election_date: date | None = None,
    category: str = "General Primary",
    election_type: str = "midterm",
    ballots_cast: int | None = None,
    registered_voters: int | None = None,
) -> Election:
    """
    Insert an Election with candidate rows directly into the database.
    Contest names are pre-registered so they aren't flagged as unknown.

    ballots_cast and registered_voters are election-wide totals (from
    elections.toml in production). Per-contest figures live on candidate rows.
    """
    from src.election_analysis_generator.normalize import normalize_contest_name

    df = make_candidates_df(rows)

    # Pre-register all contest names to suppress flags
    for raw in df["contest_name_raw"].unique():
        normalized = normalize_contest_name(raw)
        db.register_contest_name(normalized, year)

    election = Election(
        id=None,
        name=name,
        year=year,
        election_date=election_date,
        results_last_updated=None,
        summary_file=f"{name.lower().replace(' ', '-')}.csv",
        category=category,
        election_type=election_type,
        ballots_cast=ballots_cast,
        registered_voters=registered_voters,
    )
    election, _ = db.insert_election(election, df)
    assert election.id is not None, "election must have an id after insert"  # nosec B101
    db.register_file(election.summary_file, election.id)
    return election
