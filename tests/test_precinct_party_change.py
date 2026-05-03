"""
test_precinct_party_change.py
-----------------------------
Tests proving that a candidate who changes party between elections has the
correct party reflected in precinct-level data for each election.

Background
----------
``candidate_precinct_results`` has no ``party`` column of its own. Party is
resolved at query time via a LEFT JOIN to ``candidates`` on
    (election_id, contest_id, choice_name)
Because ``candidates`` is scoped per election, each election's precinct rows
independently pick up the party value stored for that election — a party
change is therefore reflected automatically without any special-casing.

These tests verify that invariant end-to-end.
"""

from src.election_analysis_generator.analysis import ElectionAnalyzer
from tests.conftest import seed_election


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_precinct_row(db, election, contest_raw: str, choice_name: str, **overrides):
    """Insert one precinct result row for the given election/contest/candidate."""
    row = db._conn.execute(
        "SELECT contests.id FROM contests JOIN candidates "
        "ON contests.id = candidates.contest_id "
        "WHERE candidates.election_id = ? AND candidates.choice_name = ?",
        (election.id, choice_name),
    ).fetchone()
    if row is None:
        raise AssertionError(f"No contest found for choice_name={choice_name!r}")
    contest_id = row[0]

    row = {
        "election_id": election.id,
        "contest_id": contest_id,
        "contest_name_raw": contest_raw,
        "choice_name": choice_name,
        "precinct": "Addison 001",
        "registered_voters": 500,
        "early_votes": 10,
        "vote_by_mail": 20,
        "polling": 30,
        "provisional": 1,
        "total_votes": 61,
        **overrides,
    }
    db.insert_precinct_results([row])
    return row


# ---------------------------------------------------------------------------
# Core party-change test
# ---------------------------------------------------------------------------


class TestPartyChangeReflectedInPrecinctData:
    """
    A candidate who switches party between elections must appear with the
    correct party in precinct_turnout() for each election independently.
    """

    def test_party_change_between_elections(self, db):
        """
        Jane Smith runs as DEM in 2022 and REP in 2026.
        Her precinct rows in each election should carry the party she ran
        under *in that election*, not bleed across.
        """
        contest_raw = "FOR ATTORNEY GENERAL (Vote For 1)"

        election_2022 = seed_election(
            db,
            "2022 General Primary",
            2022,
            [{"contest_name_raw": contest_raw, "party": "DEM",
              "choice_name": "Jane Smith", "total_votes": 68000}],
        )
        election_2026 = seed_election(
            db,
            "2026 General Primary",
            2026,
            [{"contest_name_raw": contest_raw, "party": "REP",
              "choice_name": "Jane Smith", "total_votes": 43000}],
        )

        _seed_precinct_row(db, election_2022, contest_raw, "Jane Smith",
                           precinct="Addison 001", total_votes=61)
        _seed_precinct_row(db, election_2026, contest_raw, "Jane Smith",
                           precinct="Addison 001", total_votes=39)

        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout(
            "2022 General Primary", "2026 General Primary"
        )

        row_2022 = result[
            (result["election"] == "2022 General Primary")
            & (result["candidate"] == "Jane Smith")
            & (result["precinct"] == "Addison 001")
        ].iloc[0]

        row_2026 = result[
            (result["election"] == "2026 General Primary")
            & (result["candidate"] == "Jane Smith")
            & (result["precinct"] == "Addison 001")
        ].iloc[0]

        assert row_2022["party"] == "DEM", (
            f"Expected DEM in 2022, got {row_2022['party']!r}"
        )
        assert row_2026["party"] == "REP", (
            f"Expected REP in 2026, got {row_2026['party']!r}"
        )

    def test_party_change_does_not_leak_across_elections(self, db):
        """
        The 2022 party must not be overwritten by the 2026 party (or vice
        versa) when both elections are queried together.
        """
        contest_raw = "FOR ATTORNEY GENERAL (Vote For 1)"

        election_2022 = seed_election(
            db, "2022 General Primary", 2022,
            [{"contest_name_raw": contest_raw, "party": "DEM",
              "choice_name": "Jane Smith", "total_votes": 5000}],
        )
        election_2026 = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": contest_raw, "party": "REP",
              "choice_name": "Jane Smith", "total_votes": 6000}],
        )

        for precinct in ["Addison 001", "Addison 002", "Bloomingdale 001"]:
            _seed_precinct_row(db, election_2022, contest_raw, "Jane Smith",
                               precinct=precinct, total_votes=100)
            _seed_precinct_row(db, election_2026, contest_raw, "Jane Smith",
                               precinct=precinct, total_votes=90)

        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout(
            "2022 General Primary", "2026 General Primary"
        )

        parties_2022 = result[result["election"] == "2022 General Primary"]["party"].unique()
        parties_2026 = result[result["election"] == "2026 General Primary"]["party"].unique()

        assert list(parties_2022) == ["DEM"], (
            f"All 2022 precinct rows should be DEM; got {parties_2022}"
        )
        assert list(parties_2026) == ["REP"], (
            f"All 2026 precinct rows should be REP; got {parties_2026}"
        )

    def test_unchanged_candidate_party_unaffected(self, db):
        """
        A second candidate who does NOT change party must still show the
        correct (stable) party in both elections.
        """
        contest_raw = "FOR ATTORNEY GENERAL (Vote For 1)"

        election_2022 = seed_election(
            db, "2022 General Primary", 2022,
            [
                {"contest_name_raw": contest_raw, "party": "DEM",
                 "choice_name": "Jane Smith", "total_votes": 5000},
                {"contest_name_raw": contest_raw, "party": "REP",
                 "choice_name": "Bob Jones", "total_votes": 4000},
            ],
        )
        election_2026 = seed_election(
            db, "2026 General Primary", 2026,
            [
                # Jane switches to REP
                {"contest_name_raw": contest_raw, "party": "REP",
                 "choice_name": "Jane Smith", "total_votes": 6000},
                # Bob stays REP
                {"contest_name_raw": contest_raw, "party": "REP",
                 "choice_name": "Bob Jones", "total_votes": 5000},
            ],
        )

        for election, choice, votes in [
            (election_2022, "Jane Smith", 55),
            (election_2022, "Bob Jones", 45),
            (election_2026, "Jane Smith", 60),
            (election_2026, "Bob Jones", 50),
        ]:
            _seed_precinct_row(db, election, contest_raw, choice,
                               precinct="Addison 001", total_votes=votes)

        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout(
            "2022 General Primary", "2026 General Primary"
        )

        def _party(election_name, candidate):
            return result[
                (result["election"] == election_name)
                & (result["candidate"] == candidate)
            ]["party"].iloc[0]

        assert _party("2022 General Primary", "Jane Smith") == "DEM"
        assert _party("2022 General Primary", "Bob Jones") == "REP"
        assert _party("2026 General Primary", "Jane Smith") == "REP"
        assert _party("2026 General Primary", "Bob Jones") == "REP"

    def test_single_election_query_still_correct(self, db):
        """
        Querying just one election at a time (not both together) also returns
        the correct party for that election — no cross-contamination from
        data in other elections that happen to be in the DB.
        """
        contest_raw = "FOR ATTORNEY GENERAL (Vote For 1)"

        election_2022 = seed_election(
            db, "2022 General Primary", 2022,
            [{"contest_name_raw": contest_raw, "party": "DEM",
              "choice_name": "Jane Smith", "total_votes": 5000}],
        )
        election_2026 = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": contest_raw, "party": "REP",
              "choice_name": "Jane Smith", "total_votes": 6000}],
        )

        _seed_precinct_row(db, election_2022, contest_raw, "Jane Smith",
                           precinct="Addison 001", total_votes=100)
        _seed_precinct_row(db, election_2026, contest_raw, "Jane Smith",
                           precinct="Addison 001", total_votes=90)

        analyzer = ElectionAnalyzer(db)

        result_2022 = analyzer.precinct_turnout("2022 General Primary")
        result_2026 = analyzer.precinct_turnout("2026 General Primary")

        assert result_2022.iloc[0]["party"] == "DEM"
        assert result_2026.iloc[0]["party"] == "REP"
