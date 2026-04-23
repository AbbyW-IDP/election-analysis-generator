"""
Tests for election_analysis.reports
"""

from pathlib import Path

import pandas as pd
import pytest

from election_analysis.reports import (
    AnalysisEntry,
    ReportConfig,
    load_reports_config,
    run_reports,
    ANALYSIS_REGISTRY,
)
from tests.conftest import seed_election


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_reports_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "reports.toml"
    p.write_text(content)
    return p


@pytest.fixture
def db_with_elections(db):
    """Two comparable elections seeded into an in-memory DB."""
    for year, dem, rep in [(2022, 68000, 63000), (2026, 100000, 43000)]:
        seed_election(db, f"{year} General Primary", year, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "DEM",
             "total_votes": dem, "registered_voters": 636000, "ballots_cast": 145000},
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "REP",
             "total_votes": rep, "registered_voters": 636000, "ballots_cast": 145000},
        ])
    return db


# ---------------------------------------------------------------------------
# load_reports_config
# ---------------------------------------------------------------------------

class TestLoadReportsConfig:

    def test_raises_when_file_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="reports.toml"):
            load_reports_config(tmp_path / "reports.toml")

    def test_returns_list_of_report_configs(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.my-report]
output = "out.xlsx"

[[reports.my-report.analyses]]
analysis  = "turnout"
sheet     = "turnout"
""")
        result = load_reports_config(p)
        assert len(result) == 1
        assert isinstance(result[0], ReportConfig)

    def test_report_key_and_output(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.primary-comparison]
output = "election_analysis.xlsx"

[[reports.primary-comparison.analyses]]
analysis  = "turnout"
sheet     = "turnout"
""")
        result = load_reports_config(p)
        assert result[0].key == "primary-comparison"
        assert result[0].output == Path("election_analysis.xlsx")

    def test_output_defaults_to_key_dot_xlsx(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.my-report]

[[reports.my-report.analyses]]
analysis = "turnout"
sheet    = "turnout"
""")
        result = load_reports_config(p)
        assert result[0].output == Path("my-report.xlsx")

    def test_parses_analysis_entries(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis  = "pct_change_by_party"
sheet     = "my sheet"
elections = ["2022 General Primary", "2026 General Primary"]
""")
        result = load_reports_config(p)
        entry = result[0].analyses[0]
        assert isinstance(entry, AnalysisEntry)
        assert entry.analysis == "pct_change_by_party"
        assert entry.sheet == "my sheet"
        assert entry.elections == ["2022 General Primary", "2026 General Primary"]

    def test_elections_defaults_to_empty_list(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis = "turnout"
sheet    = "turnout"
""")
        result = load_reports_config(p)
        assert result[0].analyses[0].elections == []

    def test_multiple_reports(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.report-a]
[[reports.report-a.analyses]]
analysis = "turnout"
sheet    = "turnout"

[reports.report-b]
[[reports.report-b.analyses]]
analysis = "turnout"
sheet    = "turnout"
""")
        result = load_reports_config(p)
        assert len(result) == 2

    def test_multiple_analyses_in_one_report(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis  = "pct_change_by_party"
sheet     = "pct change"
elections = ["2022 General Primary", "2026 General Primary"]

[[reports.r.analyses]]
analysis  = "turnout"
sheet     = "turnout"
""")
        result = load_reports_config(p)
        assert len(result[0].analyses) == 2

    def test_raises_on_unknown_analysis(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis = "nonexistent_analysis"
sheet    = "whatever"
""")
        with pytest.raises(ValueError, match="Unknown analysis"):
            load_reports_config(p)

    def test_empty_reports_section_returns_empty_list(self, tmp_path):
        p = write_reports_toml(tmp_path, "")
        result = load_reports_config(p)
        assert result == []

    def test_comparable_only_defaults_to_true(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis  = "pct_change_by_party"
sheet     = "s"
elections = ["2022 General Primary", "2026 General Primary"]
""")
        result = load_reports_config(p)
        assert result[0].analyses[0].comparable_only is True

    def test_comparable_only_false_is_parsed(self, tmp_path):
        p = write_reports_toml(tmp_path, """
[reports.r]

[[reports.r.analyses]]
analysis        = "pct_change_by_party"
sheet           = "s"
elections       = ["2022 General Primary", "2026 General Primary"]
comparable_only = false
""")
        result = load_reports_config(p)
        assert result[0].analyses[0].comparable_only is False


# ---------------------------------------------------------------------------
# run_reports
# ---------------------------------------------------------------------------

class TestRunReports:

    def test_writes_excel_file(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry("turnout", "turnout", [])],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        assert (tmp_path / "out.xlsx").exists()

    def test_returns_list_of_paths_written(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry("turnout", "turnout", [])],
        )]
        written = run_reports(reports, db_with_elections, base_dir=tmp_path)
        assert written == [tmp_path / "out.xlsx"]

    def test_turnout_sheet_written(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry("turnout", "turnout sheet", [])],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "turnout sheet" in xl.sheet_names

    def test_pct_change_sheet_written(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry(
                "pct_change_by_party", "pct change",
                ["2022 General Primary", "2026 General Primary"],
            )],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "pct change" in xl.sheet_names

    def test_party_share_sheet_written(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry(
                "party_share", "party share",
                ["2022 General Primary", "2026 General Primary"],
            )],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "party share" in xl.sheet_names

    def test_multiple_sheets_in_one_file(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[
                AnalysisEntry("turnout", "turnout", []),
                AnalysisEntry(
                    "pct_change_by_party", "pct change",
                    ["2022 General Primary", "2026 General Primary"],
                ),
            ],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "turnout" in xl.sheet_names
        assert "pct change" in xl.sheet_names

    def test_multiple_reports_write_separate_files(self, db_with_elections, tmp_path):
        reports = [
            ReportConfig("a", Path("a.xlsx"), [AnalysisEntry("turnout", "turnout", [])]),
            ReportConfig("b", Path("b.xlsx"), [AnalysisEntry("turnout", "turnout", [])]),
        ]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        assert (tmp_path / "a.xlsx").exists()
        assert (tmp_path / "b.xlsx").exists()

    def test_skips_analysis_with_wrong_election_count(self, db_with_elections, tmp_path, capsys):
        # pct_change_by_party with only one election should skip, not crash
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[
                AnalysisEntry("pct_change_by_party", "bad sheet", ["2022 General Primary"]),
                AnalysisEntry("turnout", "turnout", []),
            ],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "bad sheet" not in xl.sheet_names
        assert "turnout" in xl.sheet_names
        captured = capsys.readouterr()
        assert "Skipped" in captured.out

    def test_turnout_with_specific_elections(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry("turnout", "turnout", ["2022 General Primary"])],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        df = pd.read_excel(tmp_path / "out.xlsx", sheet_name="turnout", index_col=0)
        assert "2022 General Primary" in df.columns
        assert "2026 General Primary" not in df.columns

    def test_comparable_only_false_passed_through(self, db, tmp_path):
        """comparable_only=False should include contests missing from one election."""
        # Seed two elections where COUNTY CLERK has no REP in 2026
        seed_election(db, "2022 General Primary", 2022, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "DEM", "total_votes": 68000},
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "REP", "total_votes": 63000},
            {"contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",     "party": "DEM", "total_votes": 65000},
            {"contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",     "party": "REP", "total_votes": 59000},
        ])
        seed_election(db, "2026 General Primary", 2026, [
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "DEM", "total_votes": 100000},
            {"contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)", "party": "REP", "total_votes": 43000},
            {"contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",     "party": "DEM", "total_votes": 95000},
            # REP absent for COUNTY CLERK in 2026
        ])
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry(
                "pct_change_by_party", "all contests",
                ["2022 General Primary", "2026 General Primary"],
                comparable_only=False,
            )],
        )]
        run_reports(reports, db, base_dir=tmp_path)
        df = pd.read_excel(tmp_path / "out.xlsx", sheet_name="all contests")
        assert "FOR COUNTY CLERK" in df["contest"].values


# ---------------------------------------------------------------------------
# ANALYSIS_REGISTRY
# ---------------------------------------------------------------------------

class TestAnalysisRegistry:

    def test_contains_all_expected_analyses(self):
        assert "pct_change_by_party" in ANALYSIS_REGISTRY
        assert "party_share" in ANALYSIS_REGISTRY
        assert "turnout" in ANALYSIS_REGISTRY
        assert "aggregated_csv" in ANALYSIS_REGISTRY

    def test_all_values_are_callable(self):
        for name, fn in ANALYSIS_REGISTRY.items():
            assert callable(fn), f"{name} is not callable"

    def test_aggregated_csv_sheet_written(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry("aggregated_csv", "raw data", [])],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        xl = pd.ExcelFile(tmp_path / "out.xlsx")
        assert "raw data" in xl.sheet_names

    def test_aggregated_csv_with_elections_filter(self, db_with_elections, tmp_path):
        reports = [ReportConfig(
            key="test",
            output=Path("out.xlsx"),
            analyses=[AnalysisEntry(
                "aggregated_csv", "raw data",
                ["2022 General Primary"],
            )],
        )]
        run_reports(reports, db_with_elections, base_dir=tmp_path)
        df = pd.read_excel(tmp_path / "out.xlsx", sheet_name="raw data")
        assert set(df["year"].unique()) == {2022}
