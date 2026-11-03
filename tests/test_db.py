"""
Tests for election_analysis.db (ElectionDatabase)
"""

from datetime import date
from pathlib import Path

import pytest

from src.election_analysis_generator.db import ElectionDatabase, DEFAULT_DB_PATH, _placeholders
from src.election_analysis_generator.analysis import ElectionAnalyzer
from src.election_analysis_generator.models import Election
from tests.conftest import make_candidates_df, seed_election


class TestPlaceholders:
    def test_single_placeholder(self):
        assert _placeholders(1) == "?"

    def test_multiple_placeholders(self):
        assert _placeholders(3) == "?,?,?"

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="n >= 1"):
            _placeholders(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="n >= 1"):
            _placeholders(-1)


class TestSchema:
    # Consolidated from seven individual test_creates_*_table methods.
    @pytest.mark.parametrize("table", [
        "elections",
        "contests",
        "contest_results",
        "contest_name_registry",
        "contest_flags",
        "contest_name_overrides",
        "source_files",
    ])
    def test_required_tables_exist(self, db, table):
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert table in tables["name"].values

    def test_idempotent(self):
        db = ElectionDatabase(":memory:")
        db._create_schema()  # second call should not raise
        db.close()

    def test_candidates_has_required_columns(self, db):
        cols = set(db.query("PRAGMA table_info(contest_results)")["name"])
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
            "INSERT INTO contest_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            (2026, "Raw Name", "NORMALIZED NAME"),
        )
        db._conn.commit()
        row = db._conn.execute("SELECT resolved FROM contest_flags").fetchone()
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
        count = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count == 2

    def test_elections_ballots_cast_comes_from_toml(self, db):
        """Elections-level ballots_cast comes from elections.toml (the Election object),
        not from CSV rows. Per-contest figures are stored on contest_results instead."""
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
        """Per-contest ballots_cast is stored on contest_results from the CSV row."""
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "ballots_cast": 55555}]
        )
        db.insert_election(sample_election, df)
        val = db.query("SELECT ballots_cast FROM contest_results").iloc[0]["ballots_cast"]
        assert val == 55555

    def test_candidates_registered_voters_comes_from_csv(self, db, sample_election):
        """Per-contest registered_voters is stored on contest_results from the CSV row."""
        df = make_candidates_df(
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "registered_voters": 77777,
                }
            ]
        )
        db.insert_election(sample_election, df)
        val = db.query("SELECT registered_voters FROM contest_results").iloc[0][
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
        name = db.query("SELECT contest_name FROM contest_results").iloc[0]["contest_name"]
        assert name == "FOR SENATOR"

    def test_candidates_stores_election_name(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        name = db.query("SELECT election_name FROM contest_results").iloc[0]["election_name"]
        assert name == "2022 General Primary"

    def test_candidates_stores_year(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        year = db.query("SELECT year FROM contest_results").iloc[0]["year"]
        assert year == 2022

    def test_normalizes_party(self, db, sample_election):
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "D"}]
        )
        db.insert_election(sample_election, df)
        party = db.query("SELECT party FROM contest_results").iloc[0]["party"]
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

    def test_election_optional_fields_roundtrip(self, db):
        """category, election_type, ballots_cast, registered_voters all survive a DB round-trip."""
        from datetime import date as dt

        election = Election(
            id=None,
            name="2022 General Primary",
            year=2022,
            election_date=dt(2022, 6, 28),
            results_last_updated=None,
            summary_file="2022-gp.csv",
            category="General Primary",
            election_type="midterm",
            ballots_cast=145051,
            registered_voters=636341,
        )
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(election, df)
        result = db.get_election_by_name("2022 General Primary")
        assert result.category == "General Primary"
        assert result.election_type == "midterm"
        assert result.ballots_cast == 145051
        assert result.registered_voters == 636341


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



class TestSeedContestNameRegistry:
    """Tests for _seed_contest_name_registry() and the removal of auto-registration."""

    @pytest.fixture
    def seed_db(self, tmp_path):
        """Return a factory that opens an in-memory DB seeded from a given CSV string."""
        def _make(contents: str, encoding: str = "utf-8", binary: bytes | None = None):
            seed_file = tmp_path / "seed.csv"
            if binary is not None:
                seed_file.write_bytes(binary)
            else:
                seed_file.write_text(contents, encoding=encoding)
            return ElectionDatabase(":memory:", contest_names_path=seed_file)
        return _make

    def test_seed_from_file_populates_registry(self, seed_db):
        """Names in the seed CSV are present in the registry after open."""
        db = seed_db("FOR ATTORNEY GENERAL\nFOR COMPTROLLER\n")
        known = db.get_known_contest_names()
        db.close()
        assert "FOR ATTORNEY GENERAL" in known
        assert "FOR COMPTROLLER" in known

    def test_seed_strips_bom(self, seed_db):
        """A UTF-8 BOM on the first line is stripped correctly."""
        db = seed_db("", binary=b"\xef\xbb\xbfFOR ATTORNEY GENERAL\nFOR COMPTROLLER\n")
        known = db.get_known_contest_names()
        db.close()
        assert "FOR ATTORNEY GENERAL" in known

    def test_seed_is_noop_when_file_absent(self, tmp_path):
        """Missing seed file does not raise; registry stays empty."""
        db = ElectionDatabase(":memory:", contest_names_path=tmp_path / "nonexistent.csv")
        known = db.get_known_contest_names()
        db.close()
        assert known == set()

    def test_seed_is_idempotent(self, seed_db):
        """Calling _seed_contest_name_registry twice does not duplicate entries."""
        db = seed_db("FOR ATTORNEY GENERAL\n")
        db._seed_contest_name_registry()  # second call
        count = db._conn.execute(
            "SELECT COUNT(*) FROM contest_name_registry WHERE contest_name = ?",
            ("FOR ATTORNEY GENERAL",),
        ).fetchone()[0]
        db.close()
        assert count == 1

    def test_seed_skips_blank_lines(self, seed_db):
        """Blank lines in the seed file are not inserted as empty-string names."""
        db = seed_db("FOR ATTORNEY GENERAL\n\nFOR COMPTROLLER\n\n")
        known = db.get_known_contest_names()
        db.close()
        assert "" not in known
        assert len(known) == 2

    def test_seed_unquotes_csv_quoted_fields(self, seed_db):
        """Names containing commas are CSV-quoted in the file; quotes must be stripped."""
        db = seed_db(
            '"DUPAGE COUNTY FOREST PRESERVE COMMISSIONER, DISTRICT 1"\n'
            "FOR ATTORNEY GENERAL\n"
        )
        known = db.get_known_contest_names()
        db.close()
        assert "DUPAGE COUNTY FOREST PRESERVE COMMISSIONER, DISTRICT 1" in known
        assert '"' not in "".join(known)

    @pytest.mark.parametrize("contest_name", [
        pytest.param("FOR ATTORNEY GENERAL", id="attorney_general"),
        pytest.param("FOR COMPTROLLER", id="comptroller"),
        pytest.param("FOR GOVERNOR AND LIEUTENANT GOVERNOR", id="governor"),
    ])
    def test_seeded_name_not_flagged_on_load(self, tmp_path, contest_name):
        """A contest name present in the seed file is not flagged when loaded."""
        seed_file = tmp_path / "seed.csv"
        seed_file.write_text(
            "FOR ATTORNEY GENERAL\nFOR COMPTROLLER\nFOR GOVERNOR AND LIEUTENANT GOVERNOR\n",
            encoding="utf-8",
        )
        fresh_db = ElectionDatabase(":memory:", contest_names_path=seed_file)
        df = make_candidates_df([{"contest_name_raw": contest_name, "party": "DEM"}])
        e = Election(
            id=None, name="2022 General Primary", year=2022,
            election_date=date(2022, 6, 28), results_last_updated=None,
            summary_file="test.csv", category="General Primary",
            election_type="midterm",
        )
        fresh_db.insert_election_with_file(e, df, "test.csv")
        flags = fresh_db.get_unresolved_flags()
        fresh_db.close()
        assert flags == []

    def test_load_does_not_auto_register_new_name(self, db, sample_election):
        """A contest name not in the seed must not be added to the registry on load.

        Previously, _upsert_contests() called INSERT OR IGNORE INTO
        contest_name_registry for every name. After the change, names only
        enter the registry via the seed file or explicit flag resolution.
        The db fixture has no seed file, so the registry starts empty and
        must stay empty after a load.
        """
        df = make_candidates_df(
            [{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        known = db.get_known_contest_names()
        assert "FOR BRAND NEW CONTEST" not in known

    def test_load_still_flags_unregistered_name(self, db, sample_election):
        """A name absent from the registry is still flagged even without auto-registration."""
        df = make_candidates_df(
            [{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        flags = db.get_unresolved_flags()
        assert any(f["contest_name"] == "FOR BRAND NEW CONTEST" for f in flags)

    def test_load_still_inserts_contest_results_for_unregistered_name(
        self, db, sample_election
    ):
        """Flagging does not block the load -- contest_results rows are still written."""
        df = make_candidates_df(
            [{"contest_name_raw": "FOR BRAND NEW CONTEST (Vote For 1)", "party": "DEM"}]
        )
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count == 1


class TestRemapByRawName:
    """Tests for remap_by_raw_name(), the primitive for flag resolution.

    Sets contest_name and contest_id on all contest_results rows matching
    contest_name_raw, regardless of what was stored before. Re-importing a
    corrected flags spreadsheet is idempotent.
    """

    def test_updates_contest_results_by_raw_name(self, db):
        """Rows with matching contest_name_raw get the new contest_name."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"},
             {"contest_name_raw": "OLD RAW NAME", "party": "REP"}],
            election_date=date(2022, 6, 28))

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        names = db.query(
            "SELECT DISTINCT contest_name FROM contest_results"
        )["contest_name"].tolist()
        assert names == ["FOR CANONICAL NAME"]

    def test_updates_contest_id_to_canonical(self, db):
        """contest_id is updated to point at the canonical contests row."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        canonical_id = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?",
            ("FOR CANONICAL NAME",),
        ).fetchone()[0]
        rows = db.query(
            "SELECT contest_id FROM contest_results WHERE contest_name = ?",
            params=["FOR CANONICAL NAME"],
        )
        assert all(rows["contest_id"] == canonical_id)

    def test_creates_canonical_contest_row_if_absent(self, db):
        """The canonical contests row is created if it does not exist yet."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "BRAND NEW CANONICAL NAME")

        # Assert
        row = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?",
            ("BRAND NEW CANONICAL NAME",),
        ).fetchone()
        assert row is not None

    def test_reuses_canonical_contest_row_if_already_exists(self, db):
        """If the canonical contests row already exists, its id is preserved."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"},
             {"contest_name_raw": "FOR CANONICAL NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))
        canonical_id_before = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?",
            ("FOR CANONICAL NAME",),
        ).fetchone()[0]

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        canonical_id_after = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?",
            ("FOR CANONICAL NAME",),
        ).fetchone()[0]
        assert canonical_id_before == canonical_id_after

    def test_returns_count_of_updated_rows(self, db):
        """Returns the number of contest_results rows updated."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"},
             {"contest_name_raw": "OLD RAW NAME", "party": "REP"}],
            election_date=date(2022, 6, 28))

        # Act
        n = db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        assert n == 2

    def test_returns_zero_when_no_rows_match(self, db):
        """Returns 0 when no rows have the given contest_name_raw."""
        # Arrange -- empty db

        # Act
        n = db.remap_by_raw_name("NONEXISTENT RAW NAME", "FOR CANONICAL NAME")

        # Assert
        assert n == 0

    def test_idempotent_on_reimport(self, db):
        """Calling remap_by_raw_name twice with the same args is safe."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")
        n = db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert -- second call still touches the rows (raw_name still matches)
        assert n == 1
        names = db.query(
            "SELECT DISTINCT contest_name FROM contest_results"
        )["contest_name"].tolist()
        assert names == ["FOR CANONICAL NAME"]

    def test_corrects_previously_wrong_import(self, db):
        """Remapping to a different canonical name on re-import corrects mistakes."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))
        db.remap_by_raw_name("OLD RAW NAME", "WRONG NAME")

        # Act -- re-import with correction
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        names = db.query(
            "SELECT DISTINCT contest_name FROM contest_results"
        )["contest_name"].tolist()
        assert names == ["FOR CANONICAL NAME"]

    def test_only_affects_rows_matching_raw_name(self, db):
        """Rows with a different contest_name_raw are not touched."""
        # Arrange
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"},
             {"contest_name_raw": "OTHER RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        other = db.query(
            "SELECT contest_name FROM contest_results WHERE contest_name_raw = ?",
            params=["OTHER RAW NAME"],
        )["contest_name"].tolist()
        assert other == ["OTHER RAW NAME"]

    def test_updates_candidate_precinct_results_contest_id(self, db):
        """candidate_precinct_results.contest_id is updated to the canonical id."""
        # Arrange
        election = seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": "OLD RAW NAME", "party": "DEM"}],
            election_date=date(2022, 6, 28))
        old_cid = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?", ("OLD RAW NAME",)
        ).fetchone()[0]
        db._conn.execute(
            "INSERT INTO candidate_precinct_results"
            " (election_id, contest_id, contest_name_raw, choice_name, precinct,"
            "  registered_voters, early_votes, vote_by_mail, polling, provisional,"
            "  total_votes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (election.id, old_cid, "OLD RAW NAME", "Jane Smith", "Precinct 001",
             1000, 100, 50, 300, 10, 460),
        )
        db._conn.commit()

        # Act
        db.remap_by_raw_name("OLD RAW NAME", "FOR CANONICAL NAME")

        # Assert
        canonical_id = db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?",
            ("FOR CANONICAL NAME",),
        ).fetchone()[0]
        precinct_cids = db._conn.execute(
            "SELECT DISTINCT contest_id FROM candidate_precinct_results"
        ).fetchall()
        assert all(row[0] == canonical_id for row in precinct_cids)

    @pytest.mark.parametrize("raw_name,expected_name", [
        pytest.param(
            "Attorney General, State of Illinois - D*",
            "FOR ATTORNEY GENERAL",
            id="attorney_general_state_of_illinois",
        ),
        pytest.param(
            "Comptroller, State of Illinois - R",
            "FOR COMPTROLLER",
            id="comptroller_state_of_illinois",
        ),
        pytest.param(
            "State Treasurer - D",
            "FOR TREASURER",
            id="treasurer_missing_for_prefix",
        ),
    ])
    def test_cross_year_name_remapping(self, db, raw_name, expected_name):
        """Realistic cross-year name pairs remap correctly end-to-end.

        raw_name is the raw contest name from an older CSV. expected_name is
        the canonical form used in later elections. remap_by_raw_name() sets
        the stored contest_name directly by raw_name, so it works correctly
        on first import and on re-import with corrections.
        """
        # Arrange
        seed_election(db, "2014 General Primary", 2014,
            [{"contest_name_raw": raw_name, "party": "DEM"},
             {"contest_name_raw": raw_name, "party": "REP"}],
            election_date=date(2014, 3, 18))
        seed_election(db, "2022 General Primary", 2022,
            [{"contest_name_raw": expected_name, "party": "DEM"},
             {"contest_name_raw": expected_name, "party": "REP"}],
            election_date=date(2022, 6, 28))

        # Act
        n = db.remap_by_raw_name(raw_name, expected_name)

        # Assert
        assert n == 2  # DEM + REP for 2014
        distinct = db.query(
            "SELECT DISTINCT contest_name FROM contest_results"
        )["contest_name"].tolist()
        assert distinct == [expected_name]


class TestForPrefixRemapping:
    """Tests for _apply_for_prefix_remapping(), called during insert_election().

    The method auto-maps normalized names that match a seed name when prefixed
    with "FOR ". For example, "COUNTY CLERK" -> "FOR COUNTY CLERK" when
    "FOR COUNTY CLERK" is in the registry.
    """

    def _make_db_with_seed(self, db, *seed_names: str) -> None:
        """Register names directly into contest_name_registry."""
        for name in seed_names:
            db._conn.execute(
                "INSERT OR IGNORE INTO contest_name_registry"
                " (contest_name, first_seen_year) VALUES (?, 0)",
                (name,),
            )
        db._conn.commit()

    @pytest.mark.parametrize("raw,expected", [
        pytest.param(
            "County Clerk - D", "FOR COUNTY CLERK",
            id="party_suffix_stripped",
        ),
        pytest.param(
            "County Clerk - R*", "FOR COUNTY CLERK",
            id="party_suffix_with_asterisk",
        ),
        pytest.param(
            "Comptroller (Vote For 1)", "FOR COMPTROLLER",
            id="vote_for_stripped",
        ),
    ])
    def test_remaps_to_for_prefixed_canonical_name(
        self, db, sample_election, raw, expected
    ):
        """Normalized names that match 'FOR <name>' in the registry are remapped."""
        # Arrange
        canonical = expected
        self._make_db_with_seed(db, canonical)
        df = make_candidates_df([{"contest_name_raw": raw, "party": "DEM"}])

        # Act
        db.insert_election(sample_election, df)

        # Assert
        names = [
            r[0]
            for r in db._conn.execute(
                "SELECT DISTINCT contest_name FROM contest_results"
            ).fetchall()
        ]
        assert names == [canonical]

    def test_remapped_name_not_flagged(self, db, sample_election):
        """A name remapped via FOR-prefix does not produce a flag."""
        # Arrange
        self._make_db_with_seed(db, "FOR COUNTY CLERK")
        df = make_candidates_df(
            [{"contest_name_raw": "County Clerk - D", "party": "DEM"}]
        )

        # Act
        db.insert_election(sample_election, df)

        # Assert
        assert db.get_unresolved_flags() == []

    def test_override_stored_for_future_loads(self, db, sample_election):
        """An override is written so future loads use the canonical name directly."""
        # Arrange
        self._make_db_with_seed(db, "FOR COUNTY CLERK")
        df = make_candidates_df(
            [{"contest_name_raw": "County Clerk - D", "party": "DEM"}]
        )

        # Act
        db.insert_election(sample_election, df)

        # Assert
        assert db.get_overrides().get("County Clerk - D") == "FOR COUNTY CLERK"

    def test_known_name_not_remapped(self, db, sample_election):
        """A name already in the registry is left unchanged."""
        # Arrange
        self._make_db_with_seed(db, "FOR SENATOR", "SENATOR")
        df = make_candidates_df(
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}]
        )

        # Act
        db.insert_election(sample_election, df)

        # Assert
        names = [
            r[0]
            for r in db._conn.execute(
                "SELECT DISTINCT contest_name FROM contest_results"
            ).fetchall()
        ]
        assert names == ["FOR SENATOR"]

    def test_unknown_name_with_no_for_match_still_flagged(self, db, sample_election):
        """A name with no FOR-prefix match in the registry is still flagged."""
        # Arrange
        self._make_db_with_seed(db, "FOR COUNTY CLERK")
        df = make_candidates_df(
            [{"contest_name_raw": "SOME BRAND NEW CONTEST", "party": "DEM"}]
        )

        # Act
        db.insert_election(sample_election, df)

        # Assert
        assert len(db.get_unresolved_flags()) == 1

    def test_second_load_of_same_raw_name_uses_stored_override(self, db):
        """After the first load stores an override, subsequent loads use it directly."""
        # Arrange
        self._make_db_with_seed(db, "FOR COUNTY CLERK")
        election_1 = Election(
            id=None, name="2014 General Primary", year=2014,
            election_date=date(2014, 3, 18), results_last_updated=None,
            summary_file="2014.csv", category="General Primary",
            election_type="midterm",
        )
        election_2 = Election(
            id=None, name="2018 General Primary", year=2018,
            election_date=date(2018, 3, 20), results_last_updated=None,
            summary_file="2018.csv", category="General Primary",
            election_type="midterm",
        )
        df = make_candidates_df(
            [{"contest_name_raw": "County Clerk - D", "party": "DEM"}]
        )

        # Act
        db.insert_election(election_1, df)
        db.insert_election(election_2, df)

        # Assert
        names = [
            r[0]
            for r in db._conn.execute(
                "SELECT DISTINCT contest_name FROM contest_results"
            ).fetchall()
        ]
        assert names == ["FOR COUNTY CLERK"]
        assert db.get_unresolved_flags() == []

class TestFlags:
    def test_empty_initially(self, db):
        assert db.get_unresolved_flags() == []

    def test_resolve_flag(self, db):
        db._conn.execute(
            "INSERT INTO contest_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            (2026, "Raw", "NORMALIZED"),
        )
        db._conn.commit()
        flag_id = db._conn.execute("SELECT id FROM contest_flags").fetchone()[0]
        db.resolve_flag(flag_id)
        assert db.get_unresolved_flags() == []

    def test_unresolved_flag_has_expected_keys(self, db):
        db._conn.execute(
            "INSERT INTO contest_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
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
            "UPDATE contest_results SET total_votes = 150 WHERE election_id = ?",
            (election.id,),
        )
        db._conn.commit()

        mismatch = db.query(
            """
            SELECT c.choice_name, c.total_votes AS summary_total, pr.detail_total,
                   c.total_votes - pr.detail_total AS diff
            FROM contest_results c
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


class TestBuildContestIdMap:
    """Unit tests for _build_contest_id_map(), which replaced the per-row SELECT."""

    def _seed_contest(self, db, name: str) -> int:
        """Insert a contest row directly and return its id."""
        db._conn.execute(
            "INSERT OR IGNORE INTO contests (contest_name, is_legislation) VALUES (?, 0)",
            (name,),
        )
        db._conn.commit()
        return db._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?", (name,)
        ).fetchone()[0]

    def test_returns_empty_dict_for_empty_list(self, db):
        assert db._build_contest_id_map([]) == {}

    def test_returns_single_mapping(self, db):
        cid = self._seed_contest(db, "FOR ATTORNEY GENERAL")
        result = db._build_contest_id_map(["FOR ATTORNEY GENERAL"])
        assert result == {"FOR ATTORNEY GENERAL": cid}

    def test_returns_multiple_mappings_in_one_query(self, db):
        cid1 = self._seed_contest(db, "FOR SENATOR")
        cid2 = self._seed_contest(db, "FOR GOVERNOR")
        result = db._build_contest_id_map(["FOR SENATOR", "FOR GOVERNOR"])
        assert result == {"FOR SENATOR": cid1, "FOR GOVERNOR": cid2}

    def test_raises_key_error_for_missing_name(self, db):
        with pytest.raises(KeyError, match="NOT IN DB"):
            db._build_contest_id_map(["NOT IN DB"])

    def test_raises_key_error_lists_all_missing_names(self, db):
        self._seed_contest(db, "FOR SENATOR")
        with pytest.raises(KeyError, match="FOR GOVERNOR"):
            db._build_contest_id_map(["FOR SENATOR", "FOR GOVERNOR"])

    def test_ids_are_integers(self, db):
        self._seed_contest(db, "FOR SENATOR")
        result = db._build_contest_id_map(["FOR SENATOR"])
        assert isinstance(result["FOR SENATOR"], int)

    def test_duplicate_names_do_not_cause_extra_queries(self, db):
        """Passing duplicate names returns one entry (set semantics from SQL IN)."""
        cid = self._seed_contest(db, "FOR SENATOR")
        # Duplicates in the input list are fine -- SQL IN deduplicates them.
        result = db._build_contest_id_map(["FOR SENATOR", "FOR SENATOR"])
        assert result == {"FOR SENATOR": cid}


class TestInsertCandidatesRefactor:
    """
    Regression tests that verify _insert_candidates() behaviour is unchanged
    after replacing iterrows + per-row SELECT with to_dict('records') + executemany.
    """

    def test_single_candidate_row_stored_correctly(self, db, sample_election):
        df = make_candidates_df([{
            "contest_name_raw": "FOR SENATOR (Vote For 1)",
            "choice_name": "Jane Smith",
            "party": "DEM",
            "total_votes": 42000.0,
            "percent_of_votes": 55.5,
            "registered_voters": 100000.0,
            "ballots_cast": 75000.0,
            "num_precinct_total": 20.0,
            "num_precinct_rptg": 20.0,
            "over_votes": 0.0,
            "under_votes": 5.0,
        }])
        db.insert_election(sample_election, df)
        row = db.query("SELECT * FROM contest_results").iloc[0]
        assert row["choice_name"] == "Jane Smith"
        assert row["party"] == "DEM"
        assert row["total_votes"] == 42000.0
        assert row["percent_of_votes"] == 55.5
        assert row["registered_voters"] == 100000.0
        assert row["ballots_cast"] == 75000.0
        assert row["num_precinct_total"] == 20.0
        assert row["num_precinct_rptg"] == 20.0
        assert row["over_votes"] == 0.0
        assert row["under_votes"] == 5.0
        assert row["election_name"] == "2022 General Primary"
        assert row["year"] == 2022

    def test_multiple_candidates_across_multiple_contests(self, db, sample_election):
        """All rows stored correctly when there are N contests x M results."""
        df = make_candidates_df([
            {"contest_name_raw": "FOR SENATOR (Vote For 1)",  "choice_name": "Alice", "party": "DEM"},
            {"contest_name_raw": "FOR SENATOR (Vote For 1)",  "choice_name": "Bob",   "party": "REP"},
            {"contest_name_raw": "FOR GOVERNOR (Vote For 1)", "choice_name": "Carol", "party": "DEM"},
            {"contest_name_raw": "FOR GOVERNOR (Vote For 1)", "choice_name": "Dave",  "party": "REP"},
        ])
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count == 4

    def test_contest_id_fk_is_correct_for_each_row(self, db, sample_election):
        """Every candidate row must reference the contest whose name matches its own."""
        df = make_candidates_df([
            {"contest_name_raw": "FOR SENATOR (Vote For 1)",  "choice_name": "Alice", "party": "DEM"},
            {"contest_name_raw": "FOR GOVERNOR (Vote For 1)", "choice_name": "Bob",   "party": "DEM"},
        ])
        db.insert_election(sample_election, df)

        rows = db.query("""
            SELECT c.choice_name, co.contest_name
            FROM contest_results c
            JOIN contests co ON co.id = c.contest_id
        """)
        alice = rows[rows["choice_name"] == "Alice"].iloc[0]
        bob   = rows[rows["choice_name"] == "Bob"].iloc[0]
        assert alice["contest_name"] == "FOR SENATOR"
        assert bob["contest_name"]   == "FOR GOVERNOR"

    def test_null_line_number_stored_as_null(self, db, sample_election):
        df = make_candidates_df([{
            "contest_name_raw": "FOR SENATOR (Vote For 1)",
            "line_number": None,
        }])
        db.insert_election(sample_election, df)
        val = db.query("SELECT line_number FROM contest_results").iloc[0]["line_number"]
        assert val is None

    def test_nan_line_number_stored_as_null(self, db, sample_election):
        df = make_candidates_df([{
            "contest_name_raw": "FOR SENATOR (Vote For 1)",
            "line_number": float("nan"),
        }])
        db.insert_election(sample_election, df)
        val = db.query("SELECT line_number FROM contest_results").iloc[0]["line_number"]
        assert val is None

    def test_integer_line_number_stored_correctly(self, db, sample_election):
        df = make_candidates_df([{
            "contest_name_raw": "FOR SENATOR (Vote For 1)",
            "line_number": 7.0,  # CSV floats are common
        }])
        db.insert_election(sample_election, df)
        val = db.query("SELECT line_number FROM contest_results").iloc[0]["line_number"]
        assert val == 7

    def test_row_count_matches_dataframe_length(self, db, sample_election):
        """executemany must insert exactly as many rows as are in the DataFrame."""
        n = 50
        rows = [
            {"contest_name_raw": "FOR SENATOR (Vote For 1)", "choice_name": f"Candidate {i}", "party": "DEM"}
            for i in range(n)
        ]
        df = make_candidates_df(rows)
        db.insert_election(sample_election, df)
        count = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count == n


class TestTurnoutOnlyElections:
    """Tests for elections loaded with metadata only (no summary CSV)."""

    def test_insert_election_with_no_summary_file(self, db):
        """An election can be inserted with summary_file=None."""
        # Arrange
        election = Election(
            id=None,
            name="2025 consolidated",
            year=2025,
            election_date=date(2025, 4, 1),
            results_last_updated=None,
            summary_file=None,
            category="Consolidated",
            election_type="midterm",
            registered_voters=636822,
            ballots_cast=50000,
        )

        # Act
        inserted = db.insert_election_metadata(election)

        # Assert
        assert inserted.id is not None
        assert inserted.summary_file is None

    def test_turnout_only_election_appears_in_list_elections(self, db):
        """A metadata-only election is returned by list_elections()."""
        # Arrange
        from src.election_analysis_generator.models import Election
        election = Election(
            id=None, name="2025 consolidated", year=2025,
            election_date=date(2025, 4, 1), results_last_updated=None,
            summary_file=None, category="Consolidated", election_type="midterm",
            registered_voters=636822, ballots_cast=50000,
        )
        db.insert_election_metadata(election)

        # Act
        analyzer = ElectionAnalyzer(db)
        elections = analyzer.list_elections()

        # Assert
        assert "2025 consolidated" in elections["name"].tolist()

    def test_turnout_works_for_metadata_only_election(self, db):
        """turnout() returns correct figures for a metadata-only election."""
        # Arrange
        from src.election_analysis_generator.models import Election
        from src.election_analysis_generator.analysis import ElectionAnalyzer
        election = Election(
            id=None, name="2025 consolidated", year=2025,
            election_date=date(2025, 4, 1), results_last_updated=None,
            summary_file=None, category="Consolidated", election_type="midterm",
            registered_voters=636822, ballots_cast=50000,
        )
        db.insert_election_metadata(election)

        # Act
        analyzer = ElectionAnalyzer(db)
        result = analyzer.turnout()

        # Assert
        assert result.loc["Registered", "2025 consolidated"] == 636822
        assert result.loc["Ballots Cast", "2025 consolidated"] == 50000

    def test_register_file_with_file_type(self, db):
        """register_file accepts a file_type parameter."""
        # Arrange
        election = seed_election(db, "2022 General Primary", 2022, [{}],
            election_date=date(2022, 6, 28))

        # Act
        db.register_file("2022-general-primary.csv", election.id, file_type="summary")
        db.register_file("2022-general-precinct.xlsx", election.id, file_type="detail")

        # Assert
        files = db.get_loaded_files()
        types = {f["filename"]: f["file_type"] for f in files}
        assert types["2022-general-primary.csv"] == "summary"
        assert types["2022-general-precinct.xlsx"] == "detail"

    def test_get_election_coverage_turnout_only(self, db):
        """get_election_coverage returns 'turnout_only' when no files registered."""
        # Arrange
        from src.election_analysis_generator.models import Election
        election = Election(
            id=None, name="2025 consolidated", year=2025,
            election_date=date(2025, 4, 1), results_last_updated=None,
            summary_file=None, category="Consolidated", election_type="midterm",
            registered_voters=636822, ballots_cast=50000,
        )
        inserted = db.insert_election_metadata(election)

        # Act
        coverage = db.get_election_coverage(inserted.id)

        # Assert
        assert coverage == "turnout_only"

    def test_get_election_coverage_metadata_sentinel(self, db):
        """get_election_coverage returns 'turnout_only' when only a metadata sentinel is registered."""
        # Arrange
        from src.election_analysis_generator.models import Election
        election = Election(
            id=None, name="2025 consolidated", year=2025,
            election_date=date(2025, 4, 1), results_last_updated=None,
            summary_file=None, category="Consolidated", election_type="midterm",
            registered_voters=636822, ballots_cast=50000,
        )
        inserted = db.insert_election_metadata(election)
        assert inserted.id is not None
        db.register_file(f"__metadata__{election.name}", inserted.id, file_type="metadata")

        # Act
        coverage = db.get_election_coverage(inserted.id)

        # Assert
        assert coverage == "turnout_only"

    def test_get_election_coverage_summary(self, db):
        """get_election_coverage returns 'summary' when only summary file loaded."""
        # Arrange
        election = seed_election(db, "2022 General Primary", 2022, [{}],
            election_date=date(2022, 6, 28))
        db.register_file("2022-general-primary.csv", election.id, file_type="summary")

        # Act
        coverage = db.get_election_coverage(election.id)

        # Assert
        assert coverage == "summary"

    def test_get_election_coverage_summary_and_precinct(self, db):
        """get_election_coverage returns 'summary_and_precinct' when both loaded."""
        # Arrange
        election = seed_election(db, "2022 General Primary", 2022, [{}],
            election_date=date(2022, 6, 28))
        db.register_file("2022-general-primary.csv", election.id, file_type="summary")
        db.register_file("2022-general-precinct.xlsx", election.id, file_type="detail")

        # Act
        coverage = db.get_election_coverage(election.id)

        # Assert
        assert coverage == "summary_and_precinct"
