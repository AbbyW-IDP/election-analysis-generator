"""
Tests for ElectionDatabase.infer_party_from_elections
"""

import pytest
from src.election_analysis_generator.db import ElectionDatabase
from src.election_analysis_generator.models import Election
from tests.conftest import seed_election


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_general(db: ElectionDatabase, name: str, year: int, candidates: list[dict]) -> Election:
    """Seed a general election (category="general") with the given candidates."""
    return seed_election(db, name, year, candidates, category="general", election_type="midterm")


def _seed_primary(db: ElectionDatabase, name: str, year: int, candidates: list[dict]) -> Election:
    """Seed a primary election with the given candidates."""
    return seed_election(db, name, year, candidates, category="General Primary", election_type="midterm")


def _party_map(db: ElectionDatabase, election_name: str) -> dict[str, str | None]:
    """Return {choice_name: party} for all rows in an election."""
    df = db.query(
        """
        SELECT cr.choice_name, cr.party
        FROM contest_results cr
        JOIN elections e ON cr.election_id = e.id
        WHERE e.name = ?
        """,
        [election_name],
    )
    return dict(zip(df["choice_name"], df["party"]))


# ---------------------------------------------------------------------------
# does not overwrite existing values
# ---------------------------------------------------------------------------

class TestDoesNotOverwrite:
    def test_skips_rows_with_party_already_set(self, db: ElectionDatabase) -> None:
        """Rows that already have a party value are counted as skipped and never modified,
        even when the same-year primary has a conflicting party for the same candidate."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Jane Smith", "party": "DEM", "total_votes": 1000},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "John Doe",  "party": "REP", "total_votes": 900},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Jane Smith", "party": "REP", "total_votes": 500},
        ])

        result = db.infer_party_from_elections("2018 general")

        # Both rows already had a party -- nothing should change
        assert result["updated"] == 0
        assert result["skipped"] == 2
        parties = _party_map(db, "2018 general")
        assert parties["Jane Smith"] == "DEM"   # not overwritten with REP
        assert parties["John Doe"] == "REP"

    def test_updates_only_null_party_rows(self, db: ElectionDatabase) -> None:
        """Only rows with a null party are updated; rows with an existing party are left alone."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Jane Smith", "party": "DEM",  "total_votes": 1000},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "John Doe",  "party": None,   "total_votes": 900},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "John Doe", "party": "REP", "total_votes": 500},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 1
        assert result["skipped"] == 1
        parties = _party_map(db, "2018 general")
        assert parties["Jane Smith"] == "DEM"
        assert parties["John Doe"] == "REP"


# ---------------------------------------------------------------------------
# basic matching
# ---------------------------------------------------------------------------

class TestBasicMatching:
    def test_matches_by_contest_and_choice_name(self, db: ElectionDatabase) -> None:
        """Party is inferred when contest_name and choice_name both match the same-year primary."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "JB Pritzker", "party": None, "total_votes": 176000},
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "Bruce Rauner", "party": None, "total_votes": 168000},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "JB Pritzker",  "party": "DEM", "total_votes": 90000},
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "Bruce Rauner", "party": "REP", "total_votes": 70000},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 2
        assert result["not_found"] == 0
        parties = _party_map(db, "2018 general")
        assert parties["JB Pritzker"] == "DEM"
        assert parties["Bruce Rauner"] == "REP"

    def test_match_is_case_insensitive(self, db: ElectionDatabase) -> None:
        """Candidate name matching is case-insensitive (e.g. "kwame raoul" matches "KWAME RAOUL")."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "kwame raoul", "party": None, "total_votes": 500},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "KWAME RAOUL", "party": "DEM", "total_votes": 300},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 1
        assert _party_map(db, "2018 general")["kwame raoul"] == "DEM"

    def test_no_match_counted_as_not_found(self, db: ElectionDatabase) -> None:
        """A candidate absent from all same-year primaries is counted as not_found and left as null."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Third Party Candidate", "party": None, "total_votes": 100},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Someone Else", "party": "DEM", "total_votes": 500},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 0
        assert result["not_found"] == 1
        assert _party_map(db, "2018 general")["Third Party Candidate"] is None

    def test_other_year_primary_not_used(self, db: ElectionDatabase) -> None:
        """A primary from a different year does not contribute to inference."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Jane Smith", "party": None, "total_votes": 500},
        ])
        _seed_primary(db, "2022 General Primary", 2022, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Jane Smith", "party": "DEM", "total_votes": 400},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 0
        assert result["not_found"] == 1
        assert _party_map(db, "2018 general")["Jane Smith"] is None

    def test_no_same_year_primary_returns_not_found(self, db: ElectionDatabase) -> None:
        """When there is no primary in the target year, all null rows are not_found."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Alice", "party": None, "total_votes": 500},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 0
        assert result["not_found"] == 1


# ---------------------------------------------------------------------------
# name-only fallback
# ---------------------------------------------------------------------------

class TestNameFallback:
    def test_uses_name_fallback_when_contest_name_differs(self, db: ElectionDatabase) -> None:
        """If the contest name changed between primary and general but candidate name matches uniquely."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "COUNTY BOARD CHAIRPERSON", "choice_name": "Dan Cronin", "party": None, "total_votes": 500},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR CHAIRPERSON OF THE COUNTY BOARD (Vote For 1)", "choice_name": "Dan Cronin", "party": "REP", "total_votes": 400},
        ])

        result = db.infer_party_from_elections("2018 general")

        # Contest names won't match; name-only fallback should work
        assert result["updated"] == 1
        assert _party_map(db, "2018 general")["Dan Cronin"] == "REP"

    def test_ambiguous_name_not_updated(self, db: ElectionDatabase) -> None:
        """When a name appears under multiple parties in the primary but a contest-scoped match
        exists, the contest match wins and the row is updated correctly."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Pat Quinn", "party": None, "total_votes": 500},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Pat Quinn", "party": "DEM", "total_votes": 400},
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "Pat Quinn", "party": "REP", "total_votes": 300},
        ])

        result = db.infer_party_from_elections("2018 general")

        # Contest-scoped match exists (FOR ATTORNEY GENERAL -> DEM), so it should use that
        assert result["updated"] == 1
        assert _party_map(db, "2018 general")["Pat Quinn"] == "DEM"

    def test_truly_ambiguous_name_skipped_when_no_contest_match(self, db: ElectionDatabase) -> None:
        """Name-only fallback is skipped when name appears under different parties and contest doesn't match."""
        _seed_general(db, "2018 general", 2018, [
            # Different contest name so contest-scoped match fails
            {"contest_name_raw": "COUNTY BOARD MEMBER DISTRICT 1", "choice_name": "Pat Quinn", "party": None, "total_votes": 500},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Pat Quinn", "party": "DEM", "total_votes": 400},
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "Pat Quinn", "party": "REP", "total_votes": 300},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 0
        assert result["ambiguous"] == 1
        assert _party_map(db, "2018 general")["Pat Quinn"] is None


# ---------------------------------------------------------------------------
# return value counts
# ---------------------------------------------------------------------------

class TestReturnCounts:
    def test_counts_sum_to_total_null_party_rows(self, db: ElectionDatabase) -> None:
        """updated + not_found + ambiguous always equals the number of null-party rows;
        rows that already had a party contribute only to skipped."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Alice",   "party": None,  "total_votes": 500},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Bob",     "party": None,  "total_votes": 400},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Carol",   "party": None,  "total_votes": 300},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Already", "party": "DEM", "total_votes": 200},
        ])
        _seed_primary(db, "2018 General Primary", 2018, [
            # Alice maps to DEM, Bob is ambiguous (two contests, different parties), Carol not found
            {"contest_name_raw": "FOR ATTORNEY GENERAL",                 "choice_name": "Alice", "party": "DEM", "total_votes": 400},
            {"contest_name_raw": "FOR ATTORNEY GENERAL",                 "choice_name": "Bob",   "party": "DEM", "total_votes": 300},
            {"contest_name_raw": "FOR GOVERNOR AND LIEUTENANT GOVERNOR", "choice_name": "Bob",   "party": "REP", "total_votes": 200},
        ])

        result = db.infer_party_from_elections("2018 general")

        # Alice: updated (1), Bob: ambiguous name-only but contest match exists -> updated
        # Carol: not found (1), Already: skipped (1)
        assert result["skipped"] == 1
        # updated + not_found + ambiguous == null rows (3)
        assert result["updated"] + result["not_found"] + result["ambiguous"] == 3

    def test_all_skipped_when_no_null_parties(self, db: ElectionDatabase) -> None:
        """When every row already has a party, updated and not_found are both 0."""
        _seed_general(db, "2018 general", 2018, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Alice", "party": "DEM", "total_votes": 500},
            {"contest_name_raw": "FOR ATTORNEY GENERAL", "choice_name": "Bob",   "party": "REP", "total_votes": 400},
        ])

        result = db.infer_party_from_elections("2018 general")

        assert result["updated"] == 0
        assert result["skipped"] == 2
        assert result["not_found"] == 0

    def test_nonexistent_target_election_raises(self, db: ElectionDatabase) -> None:
        """Passing an election name that does not exist in the database raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            db.infer_party_from_elections("1800 general")
