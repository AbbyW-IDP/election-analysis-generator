"""
models.py
---------
Dataclasses representing core domain objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Election:
    """Represents a single election event (e.g. "2022 General Primary")."""

    id: int | None
    name: str
    year: int
    summary_file: str
    category: str = ""
    election_type: str = ""
    election_date: date | None = None
    results_last_updated: date | None = None
    ballots_cast: int | None = None
    registered_voters: int | None = None


@dataclass
class Contest:
    """A unique normalized contest name."""

    id: int | None
    contest_name: str
    is_legislation: bool = False


@dataclass
class Candidate:
    """A single candidate row from a summary file."""

    id: int | None
    contest_id: int
    election_id: int
    contest_name_raw: str
    contest_name: str
    election_name: str
    year: int
    line_number: int | None = None
    choice_name: str | None = None
    party: str | None = None
    total_votes: float | None = None
    percent_of_votes: float | None = None
    registered_voters: float | None = None
    ballots_cast: float | None = None
    num_precinct_total: float | None = None
    num_precinct_rptg: float | None = None
    over_votes: float | None = None
    under_votes: float | None = None
