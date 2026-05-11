"""
Tests for election_analysis.loader (LoadSummary)
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.election_analysis_generator.loader import (
    LoadSummary,
    _derive_election_name,
    _normalize_csv_columns,
    _parse_date,
    _validate_csv_columns,
    load_elections_config,
    REQUIRED_CSV_COLUMNS,
    OPTIONAL_CSV_COLUMNS,
)

CSV_HEADER = "line number,contest name,choice name,party name,total votes,percent of votes,registered voters,ballots cast,num Precinct total,num Precinct rptg,over votes,under votes"


def write_csv(
    tmp_path: Path, rows: list[str], filename: str = "2026-general-primary.csv"
) -> Path:
    """Write a results CSV (election source data) to tmp_path."""
    p = tmp_path / filename
    p.write_text(CSV_HEADER + "\n" + "\n".join(rows))
    return p


def write_config_csv(tmp_path: Path, entries: list[dict]) -> Path:
    """Write an elections.csv config file to tmp_path.

    Required keys in each entry dict: year, election_date, summary_file.
    The name column is intentionally absent -- it is derived by load_elections_config.
    """
    # Collect all column names across all entries, keeping a stable order.
    # year, election_date, summary_file are the required columns.
    all_cols = list(dict.fromkeys(
        ["year", "election_date", "summary_file"] +
        [k for entry in entries for k in entry
         if k not in ("year", "election_date", "summary_file", "name")]
    ))

    lines = [",".join(all_cols)]
    for entry in entries:
        row = [str(entry.get(col, "")) for col in all_cols]
        lines.append(",".join(row))

    p = tmp_path / "elections.csv"
    p.write_text("\n".join(lines) + "\n")
    return p


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    @pytest.mark.parametrize("raw, expected", [
        ("2026-03-17",  date(2026, 3, 17)),
        ("3/18/2014",   date(2014, 3, 18)),
        ("11/05/2024",  date(2024, 11, 5)),
        ("2022-12-31",  date(2022, 12, 31)),
        ("6/1/2020",    date(2020, 6, 1)),
    ])
    def test_parses_known_formats(self, raw, expected):
        assert _parse_date(raw) == expected

    @pytest.mark.parametrize("bad", [
        "18-03-2014",
        "not-a-date",
        "",
    ])
    def test_raises_on_unrecognized_format(self, bad):
        with pytest.raises(ValueError):
            _parse_date(bad)


# ---------------------------------------------------------------------------
# _derive_election_name
# ---------------------------------------------------------------------------


class TestDeriveElectionName:
    @pytest.mark.parametrize("year, category, expected", [
        (2026, "General Primary", "2026 General Primary"),
        (2022, None,              "2022"),
        (2022, "",                "2022"),
        (2024, "General",         "2024 General"),
    ])
    def test_derive_election_name(self, year, category, expected):
        assert _derive_election_name(year, category) == expected


# ---------------------------------------------------------------------------
# _normalize_csv_columns
# ---------------------------------------------------------------------------


class TestNormalizeCsvColumns:
    def test_lowercases_and_underscores(self):
        df = pd.DataFrame({"Contest Name": [], "Party Name": []})
        result = _normalize_csv_columns(df)
        assert "contest_name_raw" in result.columns
        assert "party" in result.columns

    def test_renames_contest_name_to_raw(self):
        df = pd.DataFrame({"contest name": []})
        result = _normalize_csv_columns(df)
        assert "contest_name_raw" in result.columns
        assert "contest_name" not in result.columns

    def test_renames_party_name_to_party(self):
        df = pd.DataFrame({"party name": []})
        result = _normalize_csv_columns(df)
        assert "party" in result.columns

    def test_preserves_line_number(self):
        df = pd.DataFrame({"line number": [1, 2]})
        result = _normalize_csv_columns(df)
        assert "line_number" in result.columns


# ---------------------------------------------------------------------------
# load_elections_config
# ---------------------------------------------------------------------------


class TestLoadElectionsConfig:
    def test_returns_empty_list_when_file_missing(self, tmp_path):
        result = load_elections_config(tmp_path / "nonexistent.csv")
        assert result == []

    def test_reads_elections(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17",
              "summary_file": "2026-general-primary.csv", "category": "General Primary"}],
        )
        result = load_elections_config(csv)
        assert len(result) == 1
        assert result[0]["name"] == "2026 General Primary"

    def test_reads_multiple_elections(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [
                {"year": "2022", "election_date": "2022-06-28", "summary_file": "2022.csv"},
                {"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv"},
            ],
        )
        result = load_elections_config(csv)
        assert len(result) == 2

    def test_coerces_year_to_int(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv"}],
        )
        result = load_elections_config(csv)
        assert result[0]["year"] == 2026
        assert isinstance(result[0]["year"], int)

    def test_coerces_registered_voters_to_int(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "registered_voters": "636822"}],
        )
        result = load_elections_config(csv)
        assert result[0]["registered_voters"] == 636822
        assert isinstance(result[0]["registered_voters"], int)

    def test_coerces_ballots_cast_to_int(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "ballots_cast": "161738"}],
        )
        result = load_elections_config(csv)
        assert result[0]["ballots_cast"] == 161738

    def test_blank_optional_fields_become_none(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "ballots_cast": ""}],
        )
        result = load_elections_config(csv)
        assert result[0]["year"] == 2026
        assert result[0]["ballots_cast"] is None

    def test_missing_optional_columns_produce_none(self, tmp_path):
        # A CSV with only the required columns -- no results_last_updated, etc.
        p = tmp_path / "elections.csv"
        p.write_text("year,election_date,summary_file\n2026,2026-03-17,2026.csv\n")
        result = load_elections_config(p)
        assert result[0]["results_last_updated"] is None
        assert result[0]["registered_voters"] is None
        assert result[0]["ballots_cast"] is None

    def test_raises_when_year_column_missing(self, tmp_path):
        p = tmp_path / "elections.csv"
        p.write_text("election_date,summary_file\n2026-03-17,2026.csv\n")
        with pytest.raises(ValueError, match="year"):
            load_elections_config(p)

    def test_raises_when_election_date_column_missing(self, tmp_path):
        p = tmp_path / "elections.csv"
        p.write_text("year,summary_file\n2026,2026.csv\n")
        with pytest.raises(ValueError, match="election_date"):
            load_elections_config(p)

    def test_raises_when_summary_file_column_missing(self, tmp_path):
        p = tmp_path / "elections.csv"
        p.write_text("year,election_date\n2026,2026-03-17\n")
        with pytest.raises(ValueError, match="summary_file"):
            load_elections_config(p)

    def test_raises_on_invalid_category(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "category": "InvalidCategory"}],
        )
        with pytest.raises(ValueError, match="category"):
            load_elections_config(csv)

    def test_raises_on_invalid_election_type(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "election_type": "local"}],
        )
        with pytest.raises(ValueError, match="election_type"):
            load_elections_config(csv)

    def test_detail_file_preserved_as_string(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026.csv",
              "detail_file": "2026-detail.xlsx"}],
        )
        result = load_elections_config(csv)
        assert result[0]["detail_file"] == "2026-detail.xlsx"

    def test_election_date_preserved_as_string(self, tmp_path):
        csv = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-04-07", "summary_file": "2026.csv"}],
        )
        result = load_elections_config(csv)
        assert result[0]["election_date"] == "2026-04-07"

    def test_header_whitespace_is_stripped(self, tmp_path):
        p = tmp_path / "elections.csv"
        p.write_text(" year , election_date , summary_file \n2026,2026-03-17,2026.csv\n")
        result = load_elections_config(p)
        assert result[0]["year"] == 2026


# ---------------------------------------------------------------------------
# _validate_csv_columns
# ---------------------------------------------------------------------------


class TestValidateCsvColumns:
    def _df(self, **cols):
        base = {
            "contest_name_raw": ["FOR SENATOR"],
            "party": ["DEM"],
            "total_votes": [5000.0],
        }
        base.update({k: [v] for k, v in cols.items()})
        return pd.DataFrame(base)

    def test_passes_when_all_required_present(self, tmp_path):
        df = self._df()
        result = _validate_csv_columns(df, tmp_path / "test.csv")
        assert isinstance(result, pd.DataFrame)

    def test_raises_when_contest_name_missing(self, tmp_path):
        df = pd.DataFrame({"party": ["DEM"], "total_votes": [5000.0]})
        with pytest.raises(ValueError, match="contest name"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_raises_when_party_missing(self, tmp_path):
        df = pd.DataFrame({"contest_name_raw": ["FOR SENATOR"], "total_votes": [5000.0]})
        with pytest.raises(ValueError, match="party"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_raises_when_total_votes_missing(self, tmp_path):
        df = pd.DataFrame({"contest_name_raw": ["FOR SENATOR"], "party": ["DEM"]})
        with pytest.raises(ValueError, match="total votes"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_error_names_all_missing_required_columns(self, tmp_path):
        df = pd.DataFrame({"unrelated": [1]})
        with pytest.raises(ValueError) as exc_info:
            _validate_csv_columns(df, tmp_path / "test.csv")
        msg = str(exc_info.value)
        assert "contest name" in msg
        assert "party" in msg
        assert "total votes" in msg

    def test_error_includes_filename(self, tmp_path):
        df = pd.DataFrame({"unrelated": [1]})
        with pytest.raises(ValueError, match="myfile.csv"):
            _validate_csv_columns(df, tmp_path / "myfile.csv")

    def test_optional_columns_added_as_nan_when_absent(self, tmp_path):
        df = self._df()
        result = _validate_csv_columns(df, tmp_path / "test.csv")
        for col in OPTIONAL_CSV_COLUMNS:
            assert col in result.columns, f"Optional column {col!r} not added"
            assert pd.isna(result[col].iloc[0])

    def test_existing_optional_columns_preserved(self, tmp_path):
        df = self._df(line_number=7, choice_name="Jane Smith")
        result = _validate_csv_columns(df, tmp_path / "test.csv")
        assert result["line_number"].iloc[0] == 7
        assert result["choice_name"].iloc[0] == "Jane Smith"


# ---------------------------------------------------------------------------
# REQUIRED_CSV_COLUMNS / OPTIONAL_CSV_COLUMNS constants
# ---------------------------------------------------------------------------


class TestCsvColumnConstants:
    def test_required_columns_are_post_normalisation_names(self):
        assert "contest_name_raw" in REQUIRED_CSV_COLUMNS
        assert "party" in REQUIRED_CSV_COLUMNS
        assert "total_votes" in REQUIRED_CSV_COLUMNS

    def test_optional_columns_do_not_overlap_required(self):
        assert not REQUIRED_CSV_COLUMNS & set(OPTIONAL_CSV_COLUMNS)


# ---------------------------------------------------------------------------
# LoadSummary.load_csv
# ---------------------------------------------------------------------------


class TestLoaderLoadCsv:
    def test_inserts_candidates(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
             "2,FOR SENATOR (Vote For 1),John Doe,R,4000,100.0,50000,10000,10,10,0,0"],
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": path.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        count = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count == 2

    def test_returns_election_with_id(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": path.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.id is not None
        assert election.name == "2026 General Primary"

    def test_uses_year_from_config(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
            filename="2022-general-primary.csv",
        )
        # year comes from the config dict (read from elections.csv), not inferred from filename
        config = {"name": "2022 General Primary", "year": 2022, "election_date": "2022-06-28", "summary_file": path.name}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.year == 2022

    def test_year_from_config_required(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
            filename="results.csv",
        )
        # year must be present in config -- no filename inference
        config = {"name": "2026 General Primary", "year": 2026, "election_date": "2026-03-17", "summary_file": path.name}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.year == 2026

    def test_registers_source_after_load(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": path.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        loader.load_csv(path, config)
        assert db.is_file_loaded(path.name)

    def test_flags_unrecognized_contest_names(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR BRAND NEW CONTEST (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": path.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        _, new_names = loader.load_csv(path, config)
        assert "FOR BRAND NEW CONTEST" in new_names

    def test_raises_when_required_column_missing(self, db, tmp_path):
        p = tmp_path / "2026-general-primary.csv"
        p.write_text(
            "line number,contest name,choice name,total votes\n"
            "1,FOR SENATOR,Jane Smith,5000\n"
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": p.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        with pytest.raises(ValueError, match="party"):
            loader.load_csv(p, config)

    def test_loads_csv_with_only_required_columns(self, db, tmp_path):
        p = tmp_path / "2026-general-primary.csv"
        p.write_text(
            "contest name,party name,total votes\nFOR SENATOR (Vote For 1),D,5000\n"
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": p.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(p, config)
        assert election.id is not None

    def test_election_date_from_config(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {
            "name": "2026 General Primary",
            "year": 2026,
            "summary_file": path.name,
            "election_date": "2026-03-17",
        }
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.election_date == date(2026, 3, 17)

    def test_results_last_updated_from_config(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {
            "name": "2026 General Primary",
            "year": 2026,
            "summary_file": path.name,
            "election_date": "2026-03-17",
            "results_last_updated": "2026-04-21",
        }
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.results_last_updated == date(2026, 4, 21)

    def test_results_last_updated_is_none_when_absent(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {"name": "2026 General Primary", "year": 2026, "summary_file": path.name, "election_date": "2026-03-17"}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.results_last_updated is None

    def test_results_last_updated_roundtrips_through_db(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {
            "name": "2026 General Primary",
            "year": 2026,
            "summary_file": path.name,
            "election_date": "2026-03-17",
            "results_last_updated": "2026-04-21",
        }
        loader = LoadSummary(db)
        loader.load_csv(path, config)
        retrieved = db.get_election_by_name("2026 General Primary")
        assert retrieved.results_last_updated == date(2026, 4, 21)

    def test_election_date_accepts_m_d_yyyy_format(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {
            "name": "2014 General Primary",
            "year": 2014,
            "summary_file": path.name,
            "election_date": "3/18/2014",
        }
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.election_date == date(2014, 3, 18)

    def test_results_last_updated_accepts_m_d_yyyy_format(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
        )
        config = {
            "name": "2026 General Primary",
            "year": 2026,
            "summary_file": path.name,
            "election_date": "2026-03-17",
            "results_last_updated": "4/21/2026",
        }
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        assert election.results_last_updated == date(2026, 4, 21)


# ---------------------------------------------------------------------------
# LoadSummary.sync
# ---------------------------------------------------------------------------


class TestLoaderSync:
    def test_loads_new_elections_from_config(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
            filename="2026-general-primary.csv",
        )
        config = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026-general-primary.csv", "category": "General Primary"}],
        )
        loader = LoadSummary(db)
        results = loader.sync(sources_dir=sources, config_path=config)
        assert "2026-general-primary.csv" in results

    def test_skips_already_loaded_elections(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
            filename="2026-general-primary.csv",
        )
        config = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026-general-primary.csv", "category": "General Primary"}],
        )
        loader = LoadSummary(db)
        loader.sync(sources_dir=sources, config_path=config)
        results = loader.sync(sources_dir=sources, config_path=config)
        assert "2026-general-primary.csv" not in results

    def test_database_entries_persist_after_second_sync(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            ["1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0"],
            filename="2026-general-primary.csv",
        )
        config = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "2026-general-primary.csv", "category": "General Primary"}],
        )
        loader = LoadSummary(db)
        loader.sync(sources_dir=sources, config_path=config)
        count_after_first = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        loader.sync(sources_dir=sources, config_path=config)
        count_after_second = db.query("SELECT COUNT(*) AS n FROM contest_results").iloc[0]["n"]
        assert count_after_first == count_after_second

    def test_skips_missing_source_files(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        config = write_config_csv(
            tmp_path,
            [{"year": "2026", "election_date": "2026-03-17", "summary_file": "missing.csv"}],
        )
        loader = LoadSummary(db)
        results = loader.sync(sources_dir=sources, config_path=config)
        assert results == {}

    def test_raises_if_sources_dir_missing(self, db, tmp_path):
        loader = LoadSummary(db)
        config = write_config_csv(tmp_path, [])
        with pytest.raises(FileNotFoundError):
            loader.sync(sources_dir=tmp_path / "nonexistent", config_path=config)

    def test_returns_empty_when_no_config(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        loader = LoadSummary(db)
        results = loader.sync(sources_dir=sources, config_path=tmp_path / "none.csv")
        assert results == {}
