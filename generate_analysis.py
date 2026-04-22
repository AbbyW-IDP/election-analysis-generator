"""
generate_analysis.py
--------------------
Example script showing how to use ElectionAnalyzer to produce
comparison outputs across elections.

Modify this script to run whichever analyses you need.

Usage:
    uv run python generate_analysis.py [output.xlsx]
"""

import sys
from pathlib import Path

import pandas as pd

from dupage_elections.db import ElectionDatabase, DEFAULT_DB_PATH
from dupage_elections.analysis import ElectionAnalyzer

DEFAULT_OUTPUT = Path("election_analysis.xlsx")


def main(
    output_path: Path = DEFAULT_OUTPUT,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with ElectionDatabase(db_path) as db:
        analyzer = ElectionAnalyzer(db)

        # Show all available elections
        print("Elections in database:")
        print(analyzer.list_elections()[["id", "name", "year", "election_date"]].to_string(index=False))
        print()

        # Example analyses — edit to match your actual election names
        elections = analyzer.list_elections()
        if len(elections) < 2:
            print("Need at least 2 elections loaded to run comparisons.")
            return

        names = elections["name"].tolist()

        # Most recent two elections
        recent_a, recent_b = names[-2], names[-1]
        print(f"Running pct_change_by_party: {recent_a!r} vs {recent_b!r}")
        pct_change = analyzer.pct_change_by_party(recent_a, recent_b)

        print(f"Running party_share across all elections")
        share = analyzer.party_share(*names)

        print(f"Running turnout across all elections")
        turnout = analyzer.turnout()

        print(f"\nWriting to {output_path}...")
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            turnout.to_excel(writer, sheet_name="turnout")
            pct_change.to_excel(writer, sheet_name="pct change by party", index=False)
            share.to_excel(writer, sheet_name="party share", index=False)

    print("Done.")


if __name__ == "__main__":
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    main(output_path)
