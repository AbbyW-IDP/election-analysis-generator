"""
Tests for election_analysis.db (ElectionDatabase)
"""

from datetime import date
from pathlib import Path

import pytest

from src.election_analysis_generator.db import ElectionDatabase, DEFAULT_DB_PATH
from src.election_analysis_generator.models import Election
from tests.conftest import make_candidates_df, seed_election


class TestSchema:
    def test_creates_elections_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "elections" in tables["name"].values

    def test_creates_contests_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "contests" in tables["name"].values

    def test_creates_candidates_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "candidates" in tables["name"].values

    def test_creates_contest_names_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "contest_names" in tables["name"].values

    def test_creates_contest_name_flags_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "contest_name_flags" in tables["name"].values

    def test_creates_contest_name_overrides_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "contest_name_overrides" in tables["name"].values

    def test_creates_loaded_files_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "loaded_files" in tables["name"].values

    def test_idempotent(self):
        db = ElectionDatabase(":memory:")
        db._create_schema()  # second call should not raise
        db.close()

    def test_candidates_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(candidates)")["name"])
        expected = {
            "id",
            "contest_id",
            "election_id",
            "line_number",
            "contest_name_raw",
            "contest_name",
            "election_name",
            "year",
            "choice_name",
            "party",
            "total_votes",
            "percent_of_votes",
            "registered_voters",
            "ballots_cast",
            "num_precinct_total",
            "num_precinct_rptg",
            "over_votes",
            "under_votes",
        }
        assert expected.issubset(cols)

    def test_elections_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(elections)")["name"])
        expected = {
            "id",
            "name",
            "year",
            "election_date",
            "results_last_updated",
            "summary_file",
            "ballots_cast",
            "registered_voters",
        }
        assert expected.issubset(cols)

    def test_flags_resolved_defaults_to_zero(self, db):
        db._conn.execute(
            "INSERT INTO contest_name_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            (2026, "Raw Name", "NORMALIZED NAME"),
        )
        db._conn.commit()
        row = db._conn.execute("SELECT resolved FROM contest_name_flags").fetchone()
        assert row[0] == 0


class TestContextManager:
    def test_context_manager_closes_connection(self, tmp_path):
        db_path = tmp_path / "test.db"
        with ElectionDatabase(db_path) as db:
            assert db.query("SELECT 1") is not None
        with pytest.raises(Exception):
            db.query("SELECT 1")


class TestGetConnection:
    def test_creates_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        assert not db_path.exists()
        db = ElectionDatabase(db_path)
        db.close()
        assert db_path.exists()

    def test_default_db_path_is_path(self):
        assert isinstance(DEFAULT_DB_PATH, Path)


class TestInsertElection:
    def test_inserts_election_row(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM elections").iloc[0]["n"]
        assert count == 1

    def test_returns_election_with_id(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        election, _ = db.insert_election(sample_election, df)
        assert election.id is not None

    def test_returns_new_names_list(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        _, new_names = db.insert_election(sample_election, df)
        assert isinstance(new_names, list)

    def test_inserts_candidate_rows(self, db, sample_election):
        df = make_candidates_df(
            [
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"},
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "REP"},
            ]
        )
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0]["n"]
        assert count == 2

    def test_elections_ballots_cast_comes_from_toml(self, db):
        """Elections-level ballots_cast comes from elections.toml (the Election object),
        not from CSV rows. Per-contest figures are stored on candidates instead."""
        from datetime import date

        election = Election(
            id=None,
            name="2022 General Primary",
            year=2022,
            election_date=date(2022, 6, 28),
            results_last_updated=None,
            summary_file="2022-gp.csv",
            ballots_cast=145051,
            registered_voters=636341,
        )
        df = make_candidates_df(
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "ballots_cast": 99999,
                    "registered_voters": 88888,
                }
            ]
        )
        result, _ = db.insert_election(election, df)
        # elections table should have the toml values, not the CSV row values
        assert result.ballots_cast == 145051
        assert result.registered_voters == 636341

    def test_candidates_ballots_cast_comes_from_csv(self, db, sample_election):
        """Per-contest ballots_cast is stored on candidates from the CSV row."""
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "ballots_cast": 55555}]
        )
        db.insert_election(sample_election, df)
        val = db.query("SELECT ballots_cast FROM candidates").iloc[0]["ballots_cast"]
        assert val == 55555

    def test_candidates_registered_voters_comes_from_csv(self, db, sample_election):
        """Per-contest registered_voters is stored on candidates from the CSV row."""
        df = make_candidates_df(
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "registered_voters": 77777,
                }
            ]
        )
        db.insert_election(sample_election, df)
        val = db.query("SELECT registered_voters FROM candidates").iloc[0][
            "registered_voters"
        ]
        assert val == 77777

    def test_creates_contest_for_each_unique_name(self, db, sample_election):
        df = make_candidates_df(
            [
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"},
                {"contest_name_raw": "FOR GOVERNOR (Vote For 1)", "party": "DEM"},
            ]
        )
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM contests").iloc[0]["n"]
        assert count == 2

    def test_normalizes_contest_name(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        name = db.query("SELECT contest_name FROM contests").iloc[0]["contest_name"]
        assert name == "FOR SENATOR"

    def test_candidates_stores_normalized_contest_name(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        name = db.query("SELECT contest_name FROM candidates").iloc[0]["contest_name"]
        assert name == "FOR SENATOR"

    def test_candidates_stores_election_name(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        name = db.query("SELECT election_name FROM candidates").iloc[0]["election_name"]
        assert name == "2022 General Primary"

    def test_candidates_stores_year(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        year = db.query("SELECT year FROM candidates").iloc[0]["year"]
        assert year == 2022

    def test_normalizes_party(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "D"}]
        )
        db.insert_election(sample_election, df)
        party = db.query("SELECT party FROM candidates").iloc[0]["party"]
        assert party == "DEM"

    def test_infers_legislation_when_no_party(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": None}]
        )
        db.insert_election(sample_election, df)
        is_leg = db.query("SELECT is_legislation FROM contests").iloc[0][
            "is_legislation"
        ]
        assert is_leg == 1

    def test_infers_not_legislation_when_party_present(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        is_leg = db.query("SELECT is_legislation FROM contests").iloc[0][
            "is_legislation"
        ]
        assert is_leg == 0

    def test_infers_legislation_when_party_is_empty_string(self, db, sample_election):
        """An empty string party must not be treated as a valid partisan affiliation."""
        df = make_candidates_df(
            [{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": ""}]
        )
        db.insert_election(sample_election, df)
        is_leg = db.query("SELECT is_legislation FROM contests").iloc[0][
            "is_legislation"
        ]
        assert is_leg == 1

    def test_flags_unrecognized_contest_names(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        flags = db.get_unresolved_flags()
        assert any(f["contest_name"] == "FOR BRAND NEW CONTEST" for f in flags)

    def test_insert_election_returns_new_names(self, db, sample_election):
        """New contest names are returned directly rather than requiring a registry diff."""
        df = make_candidates_df(
            [{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}]
        )
        _, new_names = db.insert_election(sample_election, df)
        assert "FOR BRAND NEW CONTEST" in new_names

    def test_no_flags_for_known_contest_names(self, db, sample_election):
        db.register_contest_name("FOR ATTORNEY GENERAL", 2022)
        df = make_candidates_df(
            [{"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        assert db.get_unresolved_flags() == []


class TestGetElection:
    def test_get_by_name(self, db):
        election = seed_election(
            db,
            "2022 General Primary",
            2022,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        result = db.get_election_by_name("2022 General Primary")
        assert result is not None
        assert result.id == election.id

    def test_get_by_id(self, db):
        election = seed_election(
            db,
            "2022 General Primary",
            2022,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        result = db.get_election_by_id(election.id)
        assert result is not None
        assert result.name == "2022 General Primary"

    def test_get_by_name_returns_none_when_not_found(self, db):
        assert db.get_election_by_name("Nonexistent Election") is None

    def test_get_by_id_returns_none_when_not_found(self, db):
        assert db.get_election_by_id(9999) is None

    def test_get_all_elections_returns_list(self, db):
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        elections = db.get_all_elections()
        assert len(elections) == 2

    def test_election_dates_roundtrip(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        result = db.get_election_by_name(sample_election.name)
        assert result.election_date == date(2022, 6, 28)
        assert result.results_last_updated == date(2022, 7, 19)


class TestSetLegislationFlag:
    def test_manual_override_to_legislation(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        db.set_contest_legislation_flag("FOR SENATOR", True)
        is_leg = db.query(
            "SELECT is_legislation FROM contests WHERE contest_name = 'FOR SENATOR'"
        ).iloc[0]["is_legislation"]
        assert is_leg == 1

    def test_manual_override_to_not_legislation(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": None}]
        )
        db.insert_election(sample_election, df)
        db.set_contest_legislation_flag("REFERENDUM QUESTION 1", False)
        is_leg = db.query(
            "SELECT is_legislation FROM contests WHERE contest_name = 'REFERENDUM QUESTION 1'"
        ).iloc[0]["is_legislation"]
        assert is_leg == 0


class TestFileRegistry:
    def test_is_file_loaded_false_initially(self, db):
        assert db.is_file_loaded("2026-general-primary.csv") is False

    def test_is_file_loaded_true_after_registering(self, db):
        election = seed_election(
            db,
            "2026 General Primary",
            2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        assert db.is_file_loaded(election.summary_file)

    def test_register_file_idempotent(self, db):
        election = seed_election(
            db,
            "2026 General Primary",
            2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        db.register_file(election.summary_file, election.id)  # second call
        sources = db.get_loaded_files()
        filenames = [s["filename"] for s in sources]
        assert filenames.count(election.summary_file) == 1


class TestOverrides:
    def test_empty_initially(self, db):
        assert db.get_overrides() == {}

    def test_add_and_retrieve(self, db):
        db.add_override("Old Name (Vote For 1)", "FOR CANONICAL NAME")
        assert db.get_overrides() == {"Old Name (Vote For 1)": "FOR CANONICAL NAME"}

    def test_replaces_existing(self, db):
        db.add_override("Old Name", "FOR FIRST NAME")
        db.add_override("Old Name", "FOR SECOND NAME")
        assert db.get_overrides()["Old Name"] == "FOR SECOND NAME"


class TestFlags:
    def test_empty_initially(self, db):
        assert db.get_unresolved_flags() == []

    def test_resolve_flag(self, db):
        db._conn.execute(
            "INSERT INTO contest_name_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            (2026, "Raw", "NORMALIZED"),
        )
        db._conn.commit()
        flag_id = db._conn.execute("SELECT id FROM contest_name_flags").fetchone()[0]
        db.resolve_flag(flag_id)
        assert db.get_unresolved_flags() == []

    def test_unresolved_flag_has_expected_keys(self, db):
        db._conn.execute(
            "INSERT INTO contest_name_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            (2026, "Raw", "NORMALIZED"),
        )
        db._conn.commit()
        flag = db.get_unresolved_flags()[0]
        assert {"id", "year", "contest_name_raw", "contest_name"}.issubset(flag.keys())


def _seed_precinct_election(db):
    """Seed a minimal election + contest and return (election, contest_id)."""
    election = seed_election(
        db,
        "2026 General Primary",
        2026,
        [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
    )
    contest_id = db._conn.execute("SELECT id FROM contests").fetchone()[0]
    return election, contest_id


def _make_precinct_row(election_id, contest_id, **overrides):
    """Return a minimal valid precinct result dict."""
    row = {
        "election_id": election_id,
        "contest_id": contest_id,
        "contest_name_raw": "FOR SENATOR (Vote For 1)",
        "choice_name": "Jane Smith",
        "precinct": "Addison 001",
        "registered_voters": 500,
        "early_votes": 10,
        "vote_by_mail": 20,
        "polling": 30,
        "provisional": 1,
        "total_votes": 61,
    }
    row.update(overrides)
    return row


class TestPrecinctResultsSchema:
    def test_creates_candidate_precinct_results_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "candidate_precinct_results" in tables["name"].values

    def test_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(candidate_precinct_results)")["name"])
        expected = {
            "id",
            "election_id",
            "contest_id",
            "contest_name_raw",
            "choice_name",
            "precinct",
            "registered_voters",
            "early_votes",
            "vote_by_mail",
            "polling",
            "provisional",
            "total_votes",
        }
        assert expected.issubset(cols)

    def test_indexes_exist(self, db):
        indexes = db.query(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )["name"].values
        assert "idx_precinct_results_election" in indexes
        assert "idx_precinct_results_contest" in indexes
        assert "idx_precinct_results_precinct" in indexes

    def test_idempotent(self):
        db = ElectionDatabase(":memory:")
        db._create_schema()  # second call should not raise
        db.close()


class TestInsertPrecinctResults:
    def test_inserts_row(self, db):
        election, contest_id = _seed_precinct_election(db)
        row = _make_precinct_row(election.id, contest_id)
        db.insert_precinct_results([row])
        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count == 1

    def test_all_columns_stored_correctly(self, db):
        election, contest_id = _seed_precinct_election(db)
        row = _make_precinct_row(election.id, contest_id)
        db.insert_precinct_results([row])
        result = db.query("SELECT * FROM candidate_precinct_results").iloc[0]
        assert result["election_id"] == election.id
        assert result["contest_id"] == contest_id
        assert result["contest_name_raw"] == "FOR SENATOR (Vote For 1)"
        assert result["choice_name"] == "Jane Smith"
        assert result["precinct"] == "Addison 001"
        assert result["registered_voters"] == 500
        assert result["early_votes"] == 10
        assert result["vote_by_mail"] == 20
        assert result["polling"] == 30
        assert result["provisional"] == 1
        assert result["total_votes"] == 61

    def test_duplicate_is_ignored(self, db):
        election, contest_id = _seed_precinct_election(db)
        row = _make_precinct_row(election.id, contest_id)
        db.insert_precinct_results([row])
        db.insert_precinct_results([row])  # second call with same row
        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count == 1

    def test_multiple_candidates_same_precinct(self, db):
        election, contest_id = _seed_precinct_election(db)
        rows = [
            _make_precinct_row(election.id, contest_id, choice_name="Jane Smith", total_votes=61),
            _make_precinct_row(election.id, contest_id, choice_name="John Doe", total_votes=39),
        ]
        db.insert_precinct_results(rows)
        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count == 2

    def test_multiple_precincts_same_candidate(self, db):
        election, contest_id = _seed_precinct_election(db)
        rows = [
            _make_precinct_row(election.id, contest_id, precinct="Addison 001", total_votes=61),
            _make_precinct_row(election.id, contest_id, precinct="Addison 002", total_votes=45),
        ]
        db.insert_precinct_results(rows)
        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count == 2

    def test_bad_election_id_raises(self, db):
        _, contest_id = _seed_precinct_election(db)
        row = _make_precinct_row(election_id=9999, contest_id=contest_id)
        with pytest.raises(Exception):
            db.insert_precinct_results([row])

    def test_bad_contest_id_raises(self, db):
        election, _ = _seed_precinct_election(db)
        row = _make_precinct_row(election_id=election.id, contest_id=9999)
        with pytest.raises(Exception):
            db.insert_precinct_results([row])

    def test_registered_voters_nullable(self, db):
        election, contest_id = _seed_precinct_election(db)
        row = _make_precinct_row(election.id, contest_id, registered_voters=None)
        db.insert_precinct_results([row])
        result = db.query("SELECT registered_voters FROM candidate_precinct_results").iloc[0]
        assert result["registered_voters"] is None

    def test_precinct_totals_match_summary(self, db):
        """Precinct rows summed by candidate should equal summary candidate totals."""
        election, contest_id = _seed_precinct_election(db)
        precinct_rows = [
            _make_precinct_row(election.id, contest_id, precinct="Addison 001", total_votes=61),
            _make_precinct_row(election.id, contest_id, precinct="Addison 002", total_votes=39),
            _make_precinct_row(election.id, contest_id, precinct="Addison 003", total_votes=50),
        ]
        db.insert_precinct_results(precinct_rows)

        # The summary candidate row was inserted by seed_election with total_votes=1000
        # (the make_candidates_df default). Update it to match our precinct sum (150).
        db._conn.execute(
            "UPDATE candidates SET total_votes = 150 WHERE election_id = ?",
            (election.id,),
        )
        db._conn.commit()

        mismatch = db.query(
            """
            SELECT c.choice_name, c.total_votes AS summary_total, pr.detail_total,
                   c.total_votes - pr.detail_total AS diff
            FROM candidates c
            JOIN (
                SELECT contest_id, choice_name, election_id,
                       SUM(total_votes) AS detail_total
                FROM   candidate_precinct_results
                GROUP  BY contest_id, choice_name, election_id
            ) pr
                ON  pr.contest_id  = c.contest_id
                AND pr.choice_name = c.choice_name
                AND pr.election_id = c.election_id
            WHERE c.election_id = ?
              AND diff <> 0
            """,
            params=[election.id],
        )
        assert mismatch.empty
