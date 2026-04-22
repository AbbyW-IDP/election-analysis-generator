"""
models.py
---------
Dataclasses representing the core domain objects:
  Election, Contest, Candidate
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Candidate:
    """One candidate row from an election CSV."""
    id: int | None
    line_number: int
    contest_name_raw: str
    choice_name: str | None
    party: str | None
    total_votes: float | None
    percent_of_votes: float | None
    num_precinct_total: float | None
    num_precinct_rptg: float | None
    over_votes: float | None
    under_votes: float | None


@dataclass
class Contest:
    """
    A single contest (race or legislation item) within an election.
    contest_name is the normalized name shared across elections.
    is_legislation is True for ballot measures with no partisan candidates.
    """
    id: int | None
    contest_name: str
    is_legislation: bool
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class Election:
    """
    A single election event (e.g. '2022 General Primary').
    One CSV file maps to one Election.
    ballots_cast and registered_voters are derived from the CSV on load.
    """
    id: int | None
    name: str
    year: int
    election_date: date | None
    results_last_updated: date | None
    source_file: str
    ballots_cast: int | None = None
    registered_voters: int | None = None
    contests: list[Contest] = field(default_factory=list)
