"""
Tests for LoadPrecinctDetail and ElectionAnalyzer.precinct_turnout()
"""

from pathlib import Path

import pandas as pd
import pytest

from src.election_analysis_generator.loader import LoadPrecinctDetail, LoadSummary
from src.election_analysis_generator.analysis import ElectionAnalyzer
from tests.conftest import seed_election


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_precinct_results(db, election, rows: list[dict]) -> None:
    """Insert precinct result rows into the DB for the given election."""
    contest_id = db._conn.execute(
        "SELECT id FROM contests LIMIT 1"
    ).fetchone()["id"]
    enriched = [
        {
            "election_id": election.id,
            "contest_id": contest_id,
            **row,
        }
        for row in rows
    ]
    db.insert_precinct_results(enriched)


def _make_precinct_row(**overrides) -> dict:
    defaults = {
        "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
        "choice_name": "Jane Smith",
        "precinct": "Addison 001",
        "registered_voters": 1000,
        "early_votes": 10,
        "vote_by_mail": 20,
        "polling": 50,
        "provisional": 0,
        "total_votes": 80,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# LoadSummary — verify it behaves correctly
# ---------------------------------------------------------------------------


class TestLoadSummaryInterface:
    def test_sync_raises_when_sources_dir_missing(self, db, tmp_path):
        loader = LoadSummary(db)
        with pytest.raises(FileNotFoundError):
            loader.sync(sources_dir=tmp_path / "nonexistent")

    def test_sync_returns_empty_when_no_config(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        loader = LoadSummary(db)
        result = loader.sync(
            sources_dir=sources,
            config_path=tmp_path / "missing.toml",
        )
        assert result == {}

    def test_load_csv_inserts_candidates(self, db, tmp_path):
        csv = tmp_path / "2026-general-primary.csv"
        csv.write_text(
            "line number,contest name,choice name,party name,"
            "total votes,percent of votes,registered voters,"
            "ballots cast,num Precinct total,num Precinct rptg,"
            "over votes,under votes\n"
            "1,FOR SENATOR (Vote For 1),Jane Smith,D,"
            "5000,100.0,50000,10000,10,10,0,0\n"
        )
        loader = LoadSummary(db)
        election, _ = loader.load_csv(csv, {"name": "2026 General Primary",
                                             "source_file": csv.name})
        assert election.id is not None
        count = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0]["n"]
        assert count == 1

    def test_load_csv_registers_source(self, db, tmp_path):
        csv = tmp_path / "2026-general-primary.csv"
        csv.write_text(
            "contest name,party name,total votes\n"
            "FOR SENATOR (Vote For 1),D,5000\n"
        )
        loader = LoadSummary(db)
        loader.load_csv(csv, {"name": "2026 General Primary",
                               "source_file": csv.name})
        assert db.is_source_loaded(csv.name)


# ---------------------------------------------------------------------------
# LoadPrecinctDetail — unit tests using a synthetic minimal workbook
# ---------------------------------------------------------------------------


def _make_minimal_workbook(tmp_path: Path, rows: list[tuple], sheet_name: str = "2") -> Path:
    """
    Write a minimal .xlsx that mimics the real detail format for a
    single-candidate, single-precinct sheet.
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    for row in rows:
        ws.append(row)

    path = tmp_path / "detail.xlsx"
    wb.save(path)
    return path


def _standard_sheet_rows(
    contest_raw: str = "FOR SENATOR (Vote For 1)",
    candidate: str = "Jane Smith",
    precinct: str = "Addison 001",
    registered: int = 1000,
    early: int = 10,
    vbm: int = 20,
    polling: int = 50,
    provisional: int = 0,
    total: int = 80,
) -> list[tuple]:
    """Four rows that match the real detail workbook layout (one candidate)."""
    return [
        # row 0: contest name
        (contest_raw,) + (None,) * 7,
        # row 1: candidate name at col index 2
        (None, None, candidate, None, None, None, None, None),
        # row 2: column headers
        ("Precinct", "Registered Voters", "Early", "Vote by Mail",
         "Polling", "Provisional", "Total Votes", "Total"),
        # row 3: data
        (precinct, registered, early, vbm, polling, provisional, total,
         early + vbm + polling + provisional),
        # row 4: total row (should be skipped)
        ("Total:", registered, early, vbm, polling, provisional, total,
         early + vbm + polling + provisional),
    ]


class TestLoadPrecinctDetailInit:
    def test_raises_when_election_id_is_none(self, db, tmp_path):
        from src.election_analysis_generator.models import Election

        election = Election(
            id=None, name="Test", year=2026,
            source_file="test.csv",
        )
        path = tmp_path / "detail.xlsx"
        path.write_bytes(b"")
        loader = LoadPrecinctDetail(db)
        with pytest.raises(ValueError, match="no database id"):
            loader.load_detail_excel(path, election)

    def test_raises_when_file_missing(self, db):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 5000}],
        )
        loader = LoadPrecinctDetail(db)
        with pytest.raises(FileNotFoundError):
            loader.load_detail_excel(Path("/nonexistent/detail.xlsx"), election)


class TestLoadPrecinctDetailParsing:
    def test_inserts_rows_for_known_contest(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        rows = _standard_sheet_rows("FOR SENATOR (Vote For 1)", "Jane Smith")
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        inserted = loader.load_detail_excel(path, election)
        assert inserted == 1

    def test_skips_total_row(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        rows = _standard_sheet_rows()
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        loader.load_detail_excel(path, election)
        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        # Only 1 data row, not 2 (Total: is skipped)
        assert count == 1

    def test_skips_no_candidate_marker(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 0}],
        )
        rows = _standard_sheet_rows(candidate="NO CANDIDATE/CANDIDATO", total=0)
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        inserted = loader.load_detail_excel(path, election)
        assert inserted == 0

    def test_skips_unknown_contest(self, db, tmp_path):
        """Sheets for contests not in the DB should be silently skipped."""
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 5000}],
        )
        rows = _standard_sheet_rows("FOR BRAND NEW CONTEST (Vote For 1)", "Bob")
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        inserted = loader.load_detail_excel(path, election)
        assert inserted == 0

    def test_stores_vote_breakdown(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        rows = _standard_sheet_rows(
            early=10, vbm=20, polling=50, provisional=1, total=81
        )
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        loader.load_detail_excel(path, election)

        result = db.query("SELECT * FROM candidate_precinct_results").iloc[0]
        assert result["early_votes"] == 10
        assert result["vote_by_mail"] == 20
        assert result["polling"] == 50
        assert result["provisional"] == 1
        assert result["total_votes"] == 81

    def test_registers_source_after_load(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        rows = _standard_sheet_rows()
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        loader.load_detail_excel(path, election)
        assert db.is_source_loaded(path.name)

    def test_idempotent_second_load(self, db, tmp_path):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        rows = _standard_sheet_rows()
        path = _make_minimal_workbook(tmp_path, rows)

        loader = LoadPrecinctDetail(db)
        loader.load_detail_excel(path, election)
        loader.load_detail_excel(path, election)  # second load — should not duplicate

        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count == 1

    def test_multi_candidate_sheet(self, db, tmp_path):
        """Two candidates in one sheet produce two precinct rows."""
        election = seed_election(
            db, "2026 General Primary", 2026,
            [
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
                 "total_votes": 80, "choice_name": "Jane Smith"},
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "REP",
                 "total_votes": 60, "choice_name": "John Doe"},
            ],
        )
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "2"
        # Row 0: contest
        ws.append(("FOR SENATOR (Vote For 1)",) + (None,) * 12)
        # Row 1: two candidate names
        ws.append((None, None, "Jane Smith", None, None, None, None,
                    "John Doe", None, None, None, None, None))
        # Row 2: headers
        ws.append(("Precinct", "Registered Voters",
                   "Early", "Vote by Mail", "Polling", "Provisional", "Total Votes",
                   "Early", "Vote by Mail", "Polling", "Provisional", "Total Votes",
                   "Total"))
        # Row 3: data — Jane gets 80, John gets 60
        ws.append(("Addison 001", 1000, 10, 20, 50, 0, 80, 5, 10, 45, 0, 60, 140))
        # Row 4: Total
        ws.append(("Total:", 1000, 10, 20, 50, 0, 80, 5, 10, 45, 0, 60, 140))

        path = tmp_path / "detail.xlsx"
        wb.save(path)

        loader = LoadPrecinctDetail(db)
        inserted = loader.load_detail_excel(path, election)
        assert inserted == 2

    def test_sync_skips_already_loaded(self, db, tmp_path):
        """sync() skips detail files already in loaded_sources."""
        sources = tmp_path / "sources"
        sources.mkdir()

        rows = _standard_sheet_rows()
        path = _make_minimal_workbook(sources, rows, sheet_name="2")

        # Write a minimal elections.toml referencing the detail file
        toml = tmp_path / "elections.toml"
        toml.write_text(
            '[elections.gp]\n'
            'name = "2026 General Primary"\n'
            'source_file = "2026-general-primary.csv"\n'
            f'detail_file = "{path.name}"\n'
        )

        loader = LoadPrecinctDetail(db)
        # First sync — loads
        loader.sync(sources_dir=sources, config_path=toml)
        count_after_first = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        # Second sync — skips
        loader.sync(sources_dir=sources, config_path=toml)
        count_after_second = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results"
        ).iloc[0]["n"]
        assert count_after_first == count_after_second


# ---------------------------------------------------------------------------
# ElectionAnalyzer.precinct_turnout()
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_precinct_data(db):
    """DB seeded with one election, one contest, two precinct rows."""
    election = seed_election(
        db, "2026 General Primary", 2026,
        [
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
             "party": "DEM", "total_votes": 130, "choice_name": "Jane Smith"},
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
             "party": "REP", "total_votes": 95,  "choice_name": "John Doe"},
        ],
    )
    contest_id = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()["id"]
    db.insert_precinct_results([
        {
            "election_id": election.id, "contest_id": contest_id,
            "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
            "choice_name": "Jane Smith", "precinct": "Addison 001",
            "registered_voters": 1000, "early_votes": 10, "vote_by_mail": 20,
            "polling": 50, "provisional": 0, "total_votes": 80,
        },
        {
            "election_id": election.id, "contest_id": contest_id,
            "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
            "choice_name": "John Doe", "precinct": "Addison 001",
            "registered_voters": 1000, "early_votes": 5, "vote_by_mail": 10,
            "polling": 40, "provisional": 0, "total_votes": 55,
        },
    ])
    return db


class TestPrecinctTurnout:
    def test_returns_dataframe(self, db_with_precinct_data):
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout()
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self, db_with_precinct_data):
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout()
        for col in [
            "election", "year", "contest", "party", "candidate",
            "precinct", "registered_voters", "early_votes", "vote_by_mail",
            "polling", "provisional", "total_votes", "turnout_rate",
        ]:
            assert col in result.columns, f"Missing column: {col!r}"

    def test_turnout_rate_calculation(self, db_with_precinct_data):
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout()
        row = result[result["candidate"] == "Jane Smith"].iloc[0]
        # 80 / 1000 = 0.08
        assert abs(row["turnout_rate"] - 0.08) < 1e-9

    def test_turnout_rate_nan_when_registered_voters_is_none(self, db):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80, "choice_name": "Jane Smith"}],
        )
        contest_id = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()["id"]
        db.insert_precinct_results([{
            "election_id": election.id, "contest_id": contest_id,
            "contest_name_raw": "FOR SENATOR (Vote For 1)",
            "choice_name": "Jane Smith", "precinct": "Addison 001",
            "registered_voters": None, "early_votes": 0, "vote_by_mail": 0,
            "polling": 80, "provisional": 0, "total_votes": 80,
        }])
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert pd.isna(result.iloc[0]["turnout_rate"])

    def test_filters_to_specified_elections(self, db):
        for year in (2022, 2026):
            e = seed_election(
                db, f"{year} General Primary", year,
                [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
                  "total_votes": 80, "choice_name": "Jane Smith"}],
            )
            cid = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()["id"]
            db.insert_precinct_results([{
                "election_id": e.id, "contest_id": cid,
                "contest_name_raw": "FOR SENATOR (Vote For 1)",
                "choice_name": "Jane Smith", "precinct": "Addison 001",
                "registered_voters": 1000, "early_votes": 0, "vote_by_mail": 0,
                "polling": 80, "provisional": 0, "total_votes": 80,
            }])

        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout("2022 General Primary")
        assert set(result["year"].unique()) == {2022}

    def test_returns_all_elections_when_none_specified(self, db_with_precinct_data):
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout()
        assert len(result) == 2  # two candidate rows from the fixture

    def test_joins_party_from_candidates(self, db_with_precinct_data):
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout()
        dem_row = result[result["candidate"] == "Jane Smith"].iloc[0]
        rep_row = result[result["candidate"] == "John Doe"].iloc[0]
        assert dem_row["party"] == "DEM"
        assert rep_row["party"] == "REP"

    def test_excludes_legislation_contests(self, db):
        election = seed_election(
            db, "2026 General Primary", 2026,
            [
                {"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
                 "total_votes": 80, "choice_name": "Jane Smith"},
                {"contest_name_raw": "Referendum Question 1 (Vote For 1)",
                 "party": None, "total_votes": 200, "choice_name": "YES"},
            ],
        )
        rows = db.query("SELECT id, contest_name FROM contests")
        senator_id = int(rows[rows["contest_name"] == "FOR SENATOR"]["id"].iloc[0])
        ref_id = int(rows[rows["contest_name"] == "REFERENDUM QUESTION 1"]["id"].iloc[0])

        db.insert_precinct_results([
            {"election_id": election.id, "contest_id": senator_id,
             "contest_name_raw": "FOR SENATOR (Vote For 1)",
             "choice_name": "Jane Smith", "precinct": "Addison 001",
             "registered_voters": 1000, "early_votes": 0, "vote_by_mail": 0,
             "polling": 80, "provisional": 0, "total_votes": 80},
            {"election_id": election.id, "contest_id": ref_id,
             "contest_name_raw": "Referendum Question 1 (Vote For 1)",
             "choice_name": "YES", "precinct": "Addison 001",
             "registered_voters": 1000, "early_votes": 0, "vote_by_mail": 0,
             "polling": 200, "provisional": 0, "total_votes": 200},
        ])
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert "REFERENDUM QUESTION 1" not in result["contest"].values

    def test_returns_empty_when_no_precinct_data(self, db):
        seed_election(
            db, "2026 General Primary", 2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM",
              "total_votes": 80}],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_accepts_election_objects(self, db_with_precinct_data):
        election = db_with_precinct_data.get_election_by_name("2026 General Primary")
        analyzer = ElectionAnalyzer(db_with_precinct_data)
        result = analyzer.precinct_turnout(election)
        assert len(result) == 2
