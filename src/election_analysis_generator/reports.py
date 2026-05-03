"""
reports.py
----------
Config-driven report generation.

Reports are defined in reports.toml. Each report produces one Excel file
with one sheet per analysis entry. Run them with:

    uv run generate-analysis                       # uses reports.toml
    uv run generate-analysis my_reports.toml       # custom config path

Schema
------
Each report is a [reports.<key>] section. The report-level key determines
the output filename if ``output`` is omitted (e.g. key "2022-vs-2026"
writes "2022-vs-2026.xlsx"). Analysis entries are [[reports.<key>.analyses]]
array-of-tables.

    [reports.primary-comparison]
    output = "election_analysis.xlsx"   # optional

    [[reports.primary-comparison.analyses]]
    analysis        = "pct_change_by_party"
    sheet           = "22-26 pct change"
    elections       = ["2022 General Primary", "2026 General Primary"]
    comparable_only = false   # optional, default true

    [[reports.primary-comparison.analyses]]
    analysis  = "party_share"
    sheet     = "14-26 party share"
    elections = ["2014 General Primary", "2018 General Primary",
                 "2022 General Primary", "2026 General Primary"]

    [[reports.primary-comparison.analyses]]
    analysis  = "turnout"
    sheet     = "turnout"
    # elections omitted → all elections in the database

Supported analysis names
------------------------
- ``pct_change_by_party``   requires exactly 2 elections
- ``party_share``           requires 2+ elections
- ``turnout``               elections optional (defaults to all)
- ``aggregated_csv``        elections optional (defaults to all)

Adding future analyses
----------------------
Register the new method name in ANALYSIS_REGISTRY at the bottom of this
file. The value is a callable ``(analyzer, elections) -> pd.DataFrame``
where ``elections`` is a (possibly empty) list of election names/ids.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from .analysis import ElectionAnalyzer
from .db import ElectionDatabase

DEFAULT_REPORTS_PATH = Path("reports.toml")


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AnalysisEntry:
    """One sheet in a report."""

    analysis: str
    sheet: str
    elections: list[str] = field(default_factory=list)
    comparable_only: bool = True


@dataclass
class ReportConfig:
    """One report → one Excel file."""

    key: str
    output: Path
    analyses: list[AnalysisEntry]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_reports_config(path: Path = DEFAULT_REPORTS_PATH) -> list[ReportConfig]:
    """
    Read reports.toml and return a list of ReportConfig objects.

    Raises FileNotFoundError if the path does not exist.
    Raises ValueError if an entry references an unknown analysis name.
    """
    if not path.exists():
        raise FileNotFoundError(f"Reports config not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    reports = []
    for key, cfg in raw.get("reports", {}).items():
        output = Path(cfg.get("output", f"{key}.xlsx"))
        analyses = []
        for entry in cfg.get("analyses", []):
            name = entry["analysis"]
            if name not in ANALYSIS_REGISTRY:
                known = ", ".join(sorted(ANALYSIS_REGISTRY))
                raise ValueError(
                    f"[reports.{key}] Unknown analysis {name!r}. "
                    f"Known analyses: {known}"
                )
            analyses.append(
                AnalysisEntry(
                    analysis=name,
                    sheet=entry["sheet"],
                    elections=entry.get("elections", []),
                    comparable_only=entry.get("comparable_only", True),
                )
            )
        reports.append(ReportConfig(key=key, output=output, analyses=analyses))

    return reports


# ---------------------------------------------------------------------------
# Report runner
# ---------------------------------------------------------------------------


def run_reports(
    reports: list[ReportConfig],
    db: ElectionDatabase,
    *,
    base_dir: Path = Path("."),
) -> list[Path]:
    """
    Run all reports and write their Excel files.

    Args:
        reports:  List of ReportConfig objects (from load_reports_config).
        db:       Open ElectionDatabase to run analyses against.
        base_dir: Directory to resolve relative output paths against.

    Returns:
        List of Paths written.
    """
    analyzer = ElectionAnalyzer(db)
    written = []

    for report in reports:
        output_path = base_dir / report.output
        print(f"\nReport: {report.key!r} → {output_path}")

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            for entry in report.analyses:
                fn = ANALYSIS_REGISTRY[entry.analysis]
                comparable_label = "" if entry.comparable_only else ", all contests"
                print(
                    f"  {entry.analysis}({', '.join(entry.elections) or 'all'}{comparable_label}) → sheet {entry.sheet!r}"
                )
                try:
                    df = fn(analyzer, entry.elections, entry.comparable_only)
                except ValueError as e:
                    print(f"  ✗ Skipped: {e}")
                    continue

                # turnout returns a row-indexed DataFrame; others are flat
                index = entry.analysis == "turnout"
                df.to_excel(writer, sheet_name=entry.sheet, index=index)

        written.append(output_path)

    return written


# ---------------------------------------------------------------------------
# Analysis registry
# ---------------------------------------------------------------------------
# Each entry maps an analysis name to a callable:
#   (analyzer: ElectionAnalyzer, elections: list[str], comparable_only: bool) -> pd.DataFrame
#
# To add a new analysis:
#   1. Add a method to ElectionAnalyzer in analysis.py
#   2. Add a wrapper function below
#   3. Add one line to ANALYSIS_REGISTRY


def _run_pct_change_by_party(
    analyzer: ElectionAnalyzer,
    elections: list[str],
    comparable_only: bool = True,
) -> pd.DataFrame:
    if len(elections) != 2:
        raise ValueError("pct_change_by_party requires exactly 2 elections.")
    return analyzer.pct_change_by_party(
        elections[0], elections[1], comparable_only=comparable_only
    )


def _run_party_share(
    analyzer: ElectionAnalyzer,
    elections: list[str],
    comparable_only: bool = True,
) -> pd.DataFrame:
    if len(elections) < 2:
        raise ValueError("party_share requires at least 2 elections.")
    return analyzer.party_share(*elections, comparable_only=comparable_only)


def _run_turnout(
    analyzer: ElectionAnalyzer,
    elections: list[str],
    comparable_only: bool = True,
) -> pd.DataFrame:
    return analyzer.turnout(*elections)  # comparable_only is not applicable to turnout


def _run_aggregated_csv(
    analyzer: ElectionAnalyzer,
    elections: list[str],
    comparable_only: bool = True,
) -> pd.DataFrame:
    return analyzer.aggregated_csv(*elections)  # comparable_only not applicable


def _run_precinct_turnout(
    analyzer: ElectionAnalyzer,
    elections: list[str],
    comparable_only: bool = True,
) -> pd.DataFrame:
    return analyzer.precinct_turnout(*elections)  # comparable_only not applicable


ANALYSIS_REGISTRY: dict[
    str, Callable[[ElectionAnalyzer, list[str], bool], pd.DataFrame]
] = {
    "pct_change_by_party": _run_pct_change_by_party,
    "party_share": _run_party_share,
    "turnout": _run_turnout,
    "aggregated_csv": _run_aggregated_csv,
    "precinct_turnout": _run_precinct_turnout,
}
