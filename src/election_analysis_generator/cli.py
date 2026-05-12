"""
election_analysis_generator/cli.py
-----------------------------------
Command-line entry points for the election_analysis package.

Each function is registered as a [project.scripts] entry point in
pyproject.toml, so after `uv sync` you can run:

    sync-sources       Load any new elections defined in elections.csv
    generate-analysis  Write election_analysis.xlsx
    export-flags       Write flags_review.xlsx for spreadsheet review
    import-flags       Apply a reviewed flags_review.xlsx to the DB
    review-flags       Interactively resolve flags in the terminal
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .analysis import ElectionAnalyzer
from .db import ElectionDatabase, DEFAULT_DB_PATH
from .loader import (
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


def sync_sources() -> None:
    """Load any elections defined in elections.csv whose CSV hasn't been loaded yet."""
    parser = argparse.ArgumentParser(
        description="Load any elections defined in elections.csv whose CSV hasn't been loaded yet."
    )
    parser.add_argument(
        "sources_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCES_DIR,
        help=f"Directory containing source CSVs (default: {DEFAULT_SOURCES_DIR})",
    )
    parser.add_argument(
        "config_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to elections.csv (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview what would be loaded without writing anything to the database.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print(f"[dry run] Scanning {args.config_path} for new elections...")
    else:
        print(f"Scanning {args.config_path} for new elections...")

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        loader = LoadSummary(db)
        results = loader.sync(
            sources_dir=args.sources_dir,
            config_path=args.config_path,
            dry_run=args.dry_run,
        )

    if not results:
        if args.dry_run:
            print("Nothing new to load.")
            print("No changes made.")
        else:
            print("No new elections found.")
        return

    any_flags = False
    for filename, (election_name, new_names) in results.items():
        if args.dry_run:
            print(f"\n  [dry run] Would load: {election_name} ({filename})")
        else:
            print(f"\n  {election_name} ({filename}): loaded successfully")
        if new_names:
            any_flags = True
            print(f"  [!] {len(new_names)} unrecognized contest name(s):")
            for name in new_names:
                print(f"    {name}")

    if args.dry_run:
        print("\nNo changes made.")
        return

    if any_flags:
        print("\nRun: review-flags")
        print(" or: export-flags  (for large batches)")


def load_detail() -> None:
    """Load precinct-detail Excel for any elections defined in elections.csv."""
    parser = argparse.ArgumentParser(
        description="Load precinct-detail Excel for any elections defined in elections.csv."
    )
    parser.add_argument(
        "sources_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCES_DIR,
        help=f"Directory containing source files (default: {DEFAULT_SOURCES_DIR})",
    )
    parser.add_argument(
        "config_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to elections.csv (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser.parse_args()

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        loader = LoadPrecinctDetail(db)
        print(f"Scanning {args.config_path} for new detail files...")
        results = loader.sync(sources_dir=args.sources_dir, config_path=args.config_path)

    if not results:
        print("No new detail files found.")
        return

    for filename, election in results.items():
        print(f"  {election.name} ({filename}): loaded")


DEFAULT_OUTPUT = Path("election_analysis.xlsx")


def generate_analysis() -> None:
    """Run reports defined in reports.toml and write the results to Excel."""
    parser = argparse.ArgumentParser(
        description="Run reports defined in reports.toml and write results to Excel."
    )
    parser.add_argument(
        "reports_path",
        nargs="?",
        type=Path,
        default=DEFAULT_REPORTS_PATH,
        help=f"Path to reports.toml (default: {DEFAULT_REPORTS_PATH})",
    )
    args = parser.parse_args()
    reports_path: Path = args.reports_path

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
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

        print(f"No reports config found at {reports_path}. Running default analysis...")
        analyzer = ElectionAnalyzer(db)

        elections = analyzer.list_elections()
        print("Elections in database:")
        print(elections[["id", "name", "year", "election_date"]].to_string(index=False))
        print()

        if len(elections) < 2:
            print("Need at least 2 elections loaded to run comparisons.")
            return

        names = elections["name"].tolist()
        recent_a, recent_b = names[-2], names[-1]
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        output_path = DEFAULT_OUTPUT.with_stem(f"{DEFAULT_OUTPUT.stem}_{ts}")

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


def export_flags_cmd() -> None:
    """Write unresolved flags to flags_review.xlsx for spreadsheet review."""
    parser = argparse.ArgumentParser(
        description="Write unresolved flags to a spreadsheet for review."
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        type=Path,
        default=DEFAULT_EXPORT_PATH,
        help=f"Output path for the flags workbook (default: {DEFAULT_EXPORT_PATH})",
    )
    args = parser.parse_args()

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        n = export_flags(db, args.output_path)

    if n == 0:
        print("No unresolved flags to export.")
        return

    print(f"Exported {n} flag(s) to {args.output_path}")
    print()
    print("Next steps:")
    print("  1. Open the workbook and review the 'flags' tab")
    print("  2. Set Status to: accepted, mapped, or ignored")
    print("     For 'mapped', fill in 'Override Target' with a name from 'known_contests'")
    print("  3. Run: import-flags")


def import_flags_cmd() -> None:
    """Apply a reviewed flags_review.xlsx to the database."""
    parser = argparse.ArgumentParser(
        description="Apply a reviewed flags workbook to the database."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        default=DEFAULT_IMPORT_PATH,
        help=f"Path to the reviewed flags workbook (default: {DEFAULT_IMPORT_PATH})",
    )
    args = parser.parse_args()

    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        try:
            counts = import_flags(db, args.input_path)
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
        print(f"\n{remaining} flag(s) still unresolved. Re-export and review to continue.")


def review_flags_cmd() -> None:
    """Interactively resolve flagged contest names in the terminal."""
    with ElectionDatabase(DEFAULT_DB_PATH) as db:
        review_flags(db)
