"""
Tests for election_analysis.loader (ElectionLoader)
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.election_analysis_generator.loader import (
    ElectionLoader,
    LoadSummary,
    _normalize_csv_columns,
    _validate_csv_columns,
    _year_from_filename,
    load_elections_config,
    REQUIRED_CSV_COLUMNS,
    OPTIONAL_CSV_COLUMNS,
)

CSV_HEADER = "line number,contest name,choice name,party name,total votes,percent of votes,registered voters,ballots cast,num Precinct total,num Precinct rptg,over votes,under votes"


def write_csv(
    tmp_path: Path, rows: list[str], filename: str = "2026-general-primary.csv"
) -> Path:
    p = tmp_path / filename
    p.write_text(CSV_HEADER + "\n" + "\n".join(rows))
    return p


def write_toml(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "elections.toml"
    lines = []
    for entry in entries:
        # Derive a slug for the section key from source_file or name
        raw_key = entry.get("source_file", entry.get("name", "election"))
        slug = Path(raw_key).stem.replace(" ", "-").lower()
        lines.append(f"[elections.{slug}]")
        for k, v in entry.items():
            # Write integers without quotes; everything else as a quoted string
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                lines.append(f"{k} = {int(v)}")
            else:
                lines.append(f'{k} = "{v}"')
        lines.append("")
    p.write_text("\n".join(lines))
    return p


# ---------------------------------------------------------------------------
# _year_from_filename
# ---------------------------------------------------------------------------


class TestYearFromFilename:
    def test_extracts_year_from_standard_name(self):
        assert _year_from_filename("summary_2026.csv") == 2026

    def test_extracts_year_from_prefix(self):
        assert _year_from_filename("2022_results.csv") == 2022

    def test_extracts_year_embedded_in_name(self):
        assert _year_from_filename("results2018final.csv") == 2018

    def test_extracts_election_year_from_date_suffixed_name(self):
        assert _year_from_filename("2022-general-primary-2022-07-19.csv") == 2022

    def test_extracts_year_when_election_and_results_date_differ(self):
        assert _year_from_filename("2022-general-primary-2023-01-15.csv") == 2022

    def test_returns_none_when_no_year(self):
        assert _year_from_filename("results.csv") is None

    def test_returns_none_for_non_20xx_year(self):
        assert _year_from_filename("results_1998.csv") is None


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
        result = load_elections_config(tmp_path / "nonexistent.toml")
        assert result == []

    def test_reads_elections(self, tmp_path):
        toml = write_toml(
            tmp_path,
            [
                {
                    "name": "2026 General Primary",
                    "year": "2026",
                    "source_file": "2026-general-primary.csv",
                }
            ],
        )
        result = load_elections_config(toml)
        assert len(result) == 1
        assert result[0]["name"] == "2026 General Primary"

    def test_reads_multiple_elections(self, tmp_path):
        toml = write_toml(
            tmp_path,
            [
                {"name": "2022 General Primary", "source_file": "2022.csv"},
                {"name": "2026 General Primary", "source_file": "2026.csv"},
            ],
        )
        result = load_elections_config(toml)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _validate_csv_columns
# ---------------------------------------------------------------------------


class TestValidateCsvColumns:
    def _df(self, **cols):
        """Build a minimal DataFrame with the given columns."""
        import pandas as pd

        base = {
            "contest_name_raw": ["FOR SENATOR"],
            "party": ["DEM"],
            "total_votes": [5000.0],
        }
        base.update({k: [v] for k, v in cols.items()})
        return pd.DataFrame(base)

    def test_passes_when_all_required_present(self, tmp_path):
        import pandas as pd

        df = self._df()
        result = _validate_csv_columns(df, tmp_path / "test.csv")
        assert isinstance(result, pd.DataFrame)

    def test_raises_when_contest_name_missing(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"party": ["DEM"], "total_votes": [5000.0]})
        with pytest.raises(ValueError, match="contest name"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_raises_when_party_missing(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame(
            {"contest_name_raw": ["FOR SENATOR"], "total_votes": [5000.0]}
        )
        with pytest.raises(ValueError, match="party"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_raises_when_total_votes_missing(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"contest_name_raw": ["FOR SENATOR"], "party": ["DEM"]})
        with pytest.raises(ValueError, match="total votes"):
            _validate_csv_columns(df, tmp_path / "test.csv")

    def test_error_names_all_missing_required_columns(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"unrelated": [1]})
        with pytest.raises(ValueError) as exc_info:
            _validate_csv_columns(df, tmp_path / "test.csv")
        msg = str(exc_info.value)
        assert "contest name" in msg
        assert "party" in msg
        assert "total votes" in msg

    def test_error_includes_filename(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"unrelated": [1]})
        with pytest.raises(ValueError, match="myfile.csv"):
            _validate_csv_columns(df, tmp_path / "myfile.csv")

    def test_optional_columns_added_as_nan_when_absent(self, tmp_path):
        import pandas as pd

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
        # These are internal names, not raw CSV header names
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
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
                "2,FOR SENATOR (Vote For 1),John Doe,R,4000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {"name": "2026 General Primary", "source_file": path.name}
        loader = LoadSummary(db)
        election, _ = loader.load_csv(path, config)
        count = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0]["n"]
        assert count == 2

    def test_returns_election_with_id(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {"name": "2026 General Primary", "source_file": path.name}
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.id is not None
        assert election.name == "2026 General Primary"

    def test_infers_year_from_filename(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
            filename="2022-general-primary.csv",
        )
        config = {"name": "2022 General Primary", "source_file": path.name}
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.year == 2022

    def test_uses_year_from_config_when_provided(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
            filename="results.csv",
        )
        config = {
            "name": "2026 General Primary",
            "year": 2026,
            "source_file": path.name,
        }
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.year == 2026

    def test_registers_source_after_load(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {"name": "2026 General Primary", "source_file": path.name}
        loader = ElectionLoader(db)
        loader.load_csv(path, config)
        assert db.is_source_loaded(path.name)

    def test_flags_unrecognized_contest_names(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR BRAND NEW CONTEST (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {"name": "2026 General Primary", "source_file": path.name}
        loader = ElectionLoader(db)
        _, new_names = loader.load_csv(path, config)
        assert "FOR BRAND NEW CONTEST" in new_names

    def test_raises_when_required_column_missing(self, db, tmp_path):
        # Write a CSV that has no "party name" column
        p = tmp_path / "2026-general-primary.csv"
        p.write_text(
            "line number,contest name,choice name,total votes\n"
            "1,FOR SENATOR,Jane Smith,5000\n"
        )
        config = {"name": "2026 General Primary", "source_file": p.name}
        loader = ElectionLoader(db)
        with pytest.raises(ValueError, match="party"):
            loader.load_csv(p, config)

    def test_loads_csv_with_only_required_columns(self, db, tmp_path):
        # A minimal CSV with only the three required columns should load fine
        p = tmp_path / "2026-general-primary.csv"
        p.write_text(
            "contest name,party name,total votes\nFOR SENATOR (Vote For 1),D,5000\n"
        )
        config = {"name": "2026 General Primary", "source_file": p.name}
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(p, config)
        assert election.id is not None

    def test_election_date_from_config(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {
            "name": "2026 General Primary",
            "source_file": path.name,
            "election_date": "2026-03-17",
        }
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.election_date == date(2026, 3, 17)

    def test_results_last_updated_from_config(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {
            "name": "2026 General Primary",
            "source_file": path.name,
            "results_last_updated": "2026-04-21",
        }
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.results_last_updated == date(2026, 4, 21)

    def test_results_last_updated_is_none_when_absent(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {"name": "2026 General Primary", "source_file": path.name}
        loader = ElectionLoader(db)
        election, _ = loader.load_csv(path, config)
        assert election.results_last_updated is None

    def test_results_last_updated_roundtrips_through_db(self, db, tmp_path):
        path = write_csv(
            tmp_path,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
        )
        config = {
            "name": "2026 General Primary",
            "source_file": path.name,
            "results_last_updated": "2026-04-21",
        }
        loader = ElectionLoader(db)
        loader.load_csv(path, config)
        retrieved = db.get_election_by_name("2026 General Primary")
        assert retrieved.results_last_updated == date(2026, 4, 21)


# ---------------------------------------------------------------------------
# ElectionLoader.sync
# ---------------------------------------------------------------------------


class TestLoaderSync:
    def test_loads_new_elections_from_config(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
            filename="2026-general-primary.csv",
        )
        toml = write_toml(
            tmp_path,
            [
                {
                    "name": "2026 General Primary",
                    "source_file": "2026-general-primary.csv",
                }
            ],
        )
        loader = ElectionLoader(db)
        results = loader.sync(sources_dir=sources, config_path=toml)
        assert "2026-general-primary.csv" in results

    def test_skips_already_loaded_elections(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
            filename="2026-general-primary.csv",
        )
        toml = write_toml(
            tmp_path,
            [
                {
                    "name": "2026 General Primary",
                    "source_file": "2026-general-primary.csv",
                }
            ],
        )
        loader = ElectionLoader(db)
        loader.sync(sources_dir=sources, config_path=toml)
        results = loader.sync(sources_dir=sources, config_path=toml)
        assert "2026-general-primary.csv" not in results

    def test_database_entries_persist_after_second_sync(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        write_csv(
            sources,
            [
                "1,FOR SENATOR (Vote For 1),Jane Smith,D,5000,100.0,50000,10000,10,10,0,0",
            ],
            filename="2026-general-primary.csv",
        )
        toml = write_toml(
            tmp_path,
            [
                {
                    "name": "2026 General Primary",
                    "source_file": "2026-general-primary.csv",
                }
            ],
        )
        loader = ElectionLoader(db)
        loader.sync(sources_dir=sources, config_path=toml)
        count_after_first = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0][
            "n"
        ]
        loader.sync(sources_dir=sources, config_path=toml)
        count_after_second = db.query("SELECT COUNT(*) AS n FROM candidates").iloc[0][
            "n"
        ]
        assert count_after_first == count_after_second

    def test_skips_missing_source_files(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        toml = write_toml(
            tmp_path, [{"name": "2026 General Primary", "source_file": "missing.csv"}]
        )
        loader = ElectionLoader(db)
        results = loader.sync(sources_dir=sources, config_path=toml)
        assert results == {}

    def test_raises_if_sources_dir_missing(self, db, tmp_path):
        loader = ElectionLoader(db)
        toml = write_toml(tmp_path, [])
        with pytest.raises(FileNotFoundError):
            loader.sync(sources_dir=tmp_path / "nonexistent", config_path=toml)

    def test_returns_empty_when_no_config(self, db, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        loader = ElectionLoader(db)
        results = loader.sync(sources_dir=sources, config_path=tmp_path / "none.toml")
        assert results == {}
