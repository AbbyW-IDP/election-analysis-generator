"""
election_analysis_generator/cli.py
-----------------------
Command-line entry points for the election_analysis package.

Each function is registered as a [project.scripts] entry point in
pyproject.toml, so after `uv sync` you can run:

    sync-sources       Load any new elections defined in elections.toml
    load-detail        Load precinct-detail Excel files defined in elections.toml
    generate-analysis  Write election_analysis.xlsx
    export-flags       Write flags_review.xlsx for spreadsheet review
    import-flags       Apply a reviewed flags_review.xlsx to the DB
    review-flags       Interactively resolve flags in the terminal
"""

from __future__ import annotations

import sys
from pathlib import Path

from .db import ElectionDatabase, DEFAULT_DB_PATH
from .loader import (
    DEFAULT_SOURCES_DIR,
    DEFAULT_CONFIG_PATH,
    LoadSummary,
    LoadPrecinctDetail,
    DEFAULT_SOURCES_DIR,
    DEFAULT_CONFIG_PATH,
)
from .reports import load_reports_config, run_reports, DEFAULT_REPORTS_PATH
from .flags import (
    export_flags,
    import_flags,
    review_flags,
    DEFAULT_EXPORT_PATH,
    DEFAULT_IMPORT_PATH,
)


# ---------------------------------------------------------------------------
# sync-sources
# ---------------------------------------------------------------------------


def sync_sources() -> None:
    """Load any elections defined in elections.toml whose CSV or detail file hasn't been loaded yet."""
    sources_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCES_DIR
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONFIG_PATH

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        summary_loader = LoadSummary(db)

        print(f"Scanning {config_path} for new elections...")
        results = summary_loader.sync(sources_dir=sources_dir, config_path=config_path)

        any_flags = False
        if not results:
            print("No new elections found.")
        else:
            for filename, (election, new_names) in results.items():
                print(f"\n  {election.name} ({filename}): loaded successfully")
                if new_names:
                    any_flags = True
                    print(f"  ⚠ {len(new_names)} unrecognized contest name(s):")
                    for name in new_names:
                        print(f"    {name}")

        # Always attempt to load precinct detail files after summary CSVs
        print(f"\nScanning {config_path} for new precinct detail files...")
        detail_loader = LoadPrecinctDetail(db)
        detail_results = detail_loader.sync(sources_dir=sources_dir, config_path=config_path)

        if not detail_results:
            print("No new detail files found.")
        else:
            for filename, (election, rows_inserted) in detail_results.items():
                print(f"  {election.name} ({filename}): {rows_inserted} precinct rows inserted")

    if any_flags:
        print("\nRun: review-flags")
        print(" or: export-flags  (for large batches)")


def load_detail() -> None:
    """Load precinct-detail Excel for any elections defined in elections.toml."""
    sources_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCES_DIR
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONFIG_PATH
 
    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        loader = LoadPrecinctDetail(db)
        print(f"Scanning {config_path} for new detail files...")
        results = loader.sync(sources_dir=sources_dir, config_path=config_path)
 
    if not results:
        print("No new detail files found.")
        return
 
    for filename, (election, rows_inserted) in results.items():
        print(f"  {election.name} ({filename}): {rows_inserted} rows inserted")



# ---------------------------------------------------------------------------
# generate-analysis
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT = Path("election_analysis.xlsx")


def generate_analysis() -> None:
    """
    Run reports defined in reports.toml (or a custom path passed as the first
    argument) and write the results to Excel.

    Usage:
        uv run generate-analysis                   # uses reports.toml
        uv run generate-analysis my_reports.toml   # custom config

    If no reports.toml is found, falls back to a default run: turnout for all
    elections, pct_change_by_party and party_share for the two most recent.
    """
    from .analysis import ElectionAnalyzer

    reports_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REPORTS_PATH

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        # Config-driven path
        if reports_path.exists():
            try:
                reports = load_reports_config(reports_path)
            except ValueError as e:
                print(f"Error in {reports_path}: {e}")
                sys.exit(1)

            if not reports:
                print(f"No reports defined in {reports_path}.")
                return

            written = run_reports(reports, db)
            print(f"\nDone. Wrote {len(written)} file(s):")
            for p in written:
                print(f"  {p}")
            return

        # Fallback: default hardcoded run (no reports.toml present)
        print(f"No reports config found at {reports_path}. Running default analysis...")
        analyzer = ElectionAnalyzer(db)

        elections = analyzer.list_elections()
        print("Elections in database:")
        print(elections[["id", "name", "year", "election_date"]].to_string(index=False))
        print()

        if len(elections) < 2:
            print("Need at least 2 elections loaded to run comparisons.")
            return

        import pandas as pd

        names = elections["name"].tolist()
        recent_a, recent_b = names[-2], names[-1]
        output_path = DEFAULT_OUTPUT

        print(f"Running pct_change_by_party: {recent_a!r} vs {recent_b!r}")
        pct_change = analyzer.pct_change_by_party(recent_a, recent_b)
        print("Running party_share across all elections")
        share = analyzer.party_share(*names)
        print("Running turnout across all elections")
        turnout = analyzer.turnout()

        print(f"\nWriting to {output_path}...")
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            turnout.to_excel(writer, sheet_name="turnout")
            pct_change.to_excel(writer, sheet_name="pct change by party", index=False)
            share.to_excel(writer, sheet_name="party share", index=False)

    print("Done.")


# ---------------------------------------------------------------------------
# export-flags
# ---------------------------------------------------------------------------


def export_flags_cmd() -> None:
    """Write unresolved flags to flags_review.xlsx for spreadsheet review."""
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXPORT_PATH

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        n = export_flags(db, output_path)

    if n == 0:
        print("No unresolved flags to export.")
        return

    print(f"Exported {n} flag(s) to {output_path}")
    print()
    print("Next steps:")
    print("  1. Open the workbook and review the 'flags' tab")
    print("  2. Set Status to: accepted, mapped, or ignored")
    print(
        "     For 'mapped', fill in 'Override Target' with a name from 'known_contests'"
    )
    print("  3. Run: import-flags")


# ---------------------------------------------------------------------------
# import-flags
# ---------------------------------------------------------------------------


def import_flags_cmd() -> None:
    """Apply a reviewed flags_review.xlsx to the database."""
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMPORT_PATH

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        try:
            counts = import_flags(db, input_path)
        except FileNotFoundError as e:
            print(e)
            sys.exit(1)
        except ValueError as e:
            print(e)
            sys.exit(1)

    print("Import complete:")
    print(f"  {counts['accepted']:>5} accepted")
    print(f"  {counts['mapped']:>5} mapped")
    print(f"  {counts['ignored']:>5} ignored")
    print(f"  {counts['skipped']:>5} unreviewed (skipped)")
    if counts["errors"]:
        print(f"  {counts['errors']:>5} errors — fix and re-run")

    remaining = counts["skipped"] + counts["errors"]
    if remaining:
        print(
            f"\n{remaining} flag(s) still unresolved. Re-export and review to continue."
        )


# ---------------------------------------------------------------------------
# review-flags
# ---------------------------------------------------------------------------


def review_flags_cmd() -> None:
    """Interactively resolve flagged contest names in the terminal."""
    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        review_flags(db)
