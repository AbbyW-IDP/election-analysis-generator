"""
Tests for election_analysis.db (ElectionDatabase)
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from election_analysis.db import ElectionDatabase, DEFAULT_DB_PATH
from election_analysis.models import Election
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

    def test_creates_loaded_sources_table(self, db):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert "loaded_sources" in tables["name"].values

    def test_idempotent(self):
        db = ElectionDatabase(":memory:")
        db._create_schema()  # second call should not raise
        db.close()

    def test_candidates_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(candidates)")["name"])
        expected = {
            "id", "contest_id", "election_id", "line_number",
            "contest_name_raw", "choice_name", "party", "total_votes",
            "percent_of_votes", "num_precinct_total", "num_precinct_rptg",
            "over_votes", "under_votes",
        }
        assert expected.issubset(cols)

    def test_elections_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(elections)")["name"])
        expected = {
            "id", "name", "year", "election_date", "results_last_updated",
            "source_file", "ballots_cast", "registered_voters",
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
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM elections").iloc[0]["n"]
        assert count == 1

    def test_returns_election_with_id(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        result = db.insert_election(sample_election, df)
        assert result.id is not None

    def test_inserts_candidate_rows(self, db, sample_election):
        df = make_candidates_df([
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"},
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "REP"},
        ])
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0]["n"]
        assert count == 2

    def test_derives_ballots_cast_from_csv(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "ballots_cast": 12345}])
        result = db.insert_election(sample_election, df)
        assert result.ballots_cast == 12345

    def test_derives_registered_voters_from_csv(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "registered_voters": 99999}])
        result = db.insert_election(sample_election, df)
        assert result.registered_voters == 99999

    def test_creates_contest_for_each_unique_name(self, db, sample_election):
        df = make_candidates_df([
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"},
            {"contest_name_raw": "FOR GOVERNOR (Vote For 1)", "party": "DEM"},
        ])
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM contests").iloc[0]["n"]
        assert count == 2

    def test_normalizes_contest_name(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        name = db.query("SELECT contest_name FROM contests").iloc[0]["contest_name"]
        assert name == "FOR SENATOR"

    def test_normalizes_party(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "D"}])
        db.insert_election(sample_election, df)
        party = db.query("SELECT party FROM candidates").iloc[0]["party"]
        assert party == "DEM"

    def test_infers_legislation_when_no_party(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": None}])
        db.insert_election(sample_election, df)
        is_leg = db.query("SELECT is_legislation FROM contests").iloc[0]["is_legislation"]
        assert is_leg == 1

    def test_infers_not_legislation_when_party_present(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        is_leg = db.query("SELECT is_legislation FROM contests").iloc[0]["is_legislation"]
        assert is_leg == 0

    def test_flags_unrecognized_contest_names(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        flags = db.get_unresolved_flags()
        assert any(f["contest_name"] == "FOR BRAND NEW CONTEST" for f in flags)

    def test_no_flags_for_known_contest_names(self, db, sample_election):
        db.register_contest_name("FOR ATTORNEY GENERAL", 2022)
        df = make_candidates_df([{"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        assert db.get_unresolved_flags() == []


class TestGetElection:

    def test_get_by_name(self, db):
        election = seed_election(db, "2022 General Primary", 2022, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        result = db.get_election_by_name("2022 General Primary")
        assert result is not None
        assert result.id == election.id

    def test_get_by_id(self, db):
        election = seed_election(db, "2022 General Primary", 2022, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        result = db.get_election_by_id(election.id)
        assert result is not None
        assert result.name == "2022 General Primary"

    def test_get_by_name_returns_none_when_not_found(self, db):
        assert db.get_election_by_name("Nonexistent Election") is None

    def test_get_by_id_returns_none_when_not_found(self, db):
        assert db.get_election_by_id(9999) is None

    def test_get_all_elections_returns_list(self, db):
        seed_election(db, "2022 General Primary", 2022, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        seed_election(db, "2026 General Primary", 2026, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        elections = db.get_all_elections()
        assert len(elections) == 2

    def test_election_dates_roundtrip(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        result = db.get_election_by_name(sample_election.name)
        assert result.election_date == date(2022, 6, 28)
        assert result.results_last_updated == date(2022, 7, 19)


class TestSetLegislationFlag:

    def test_manual_override_to_legislation(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}])
        db.insert_election(sample_election, df)
        db.set_contest_legislation_flag("FOR SENATOR", True)
        is_leg = db.query("SELECT is_legislation FROM contests WHERE contest_name = 'FOR SENATOR'").iloc[0]["is_legislation"]
        assert is_leg == 1

    def test_manual_override_to_not_legislation(self, db, sample_election):
        df = make_candidates_df([{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": None}])
        db.insert_election(sample_election, df)
        db.set_contest_legislation_flag("REFERENDUM QUESTION 1", False)
        is_leg = db.query("SELECT is_legislation FROM contests WHERE contest_name = 'REFERENDUM QUESTION 1'").iloc[0]["is_legislation"]
        assert is_leg == 0


class TestSourceRegistry:

    def test_is_source_loaded_false_initially(self, db):
        assert db.is_source_loaded("2026-general-primary.csv") is False

    def test_is_source_loaded_true_after_registering(self, db):
        election = seed_election(db, "2026 General Primary", 2026, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        assert db.is_source_loaded(election.source_file)

    def test_register_source_idempotent(self, db):
        election = seed_election(db, "2026 General Primary", 2026, [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}
        ])
        db.register_source(election.source_file, election.id)  # second call
        sources = db.get_loaded_sources()
        filenames = [s["filename"] for s in sources]
        assert filenames.count(election.source_file) == 1


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
