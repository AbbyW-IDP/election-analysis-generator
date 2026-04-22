"""
setup_db.py
-----------
One-time setup: loads the historical Excel workbook into elections.db
using the election configs defined in elections.toml, then syncs any
CSVs already present in sources/.

Usage:
    uv run python setup_db.py [workbook.xlsx] [sources_dir]
"""

import sys
from pathlib import Path

from dupage_elections.db import ElectionDatabase, DEFAULT_DB_PATH
from dupage_elections.loader import (
    ElectionLoader, DEFAULT_SOURCES_DIR, DEFAULT_CONFIG_PATH,
    load_elections_config,
)

DEFAULT_EXCEL = Path("comparison_14-26_official.xlsx")


def main(
    excel_path: Path = DEFAULT_EXCEL,
    sources_dir: Path = DEFAULT_SOURCES_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with ElectionDatabase(db_path) as db:
        loader = ElectionLoader(db)
        configs = load_elections_config(DEFAULT_CONFIG_PATH)

        print(f"Loading {excel_path}...")
        results = loader.load_excel(excel_path, configs)
        for name, (election, new_names) in results.items():
            print(f"  {name}: loaded")
            if new_names:
                print(f"    ⚠  {len(new_names)} new contest name(s) registered")

        if sources_dir.exists():
            print(f"\nSyncing {sources_dir}...")
            sync_results = loader.sync(sources_dir=sources_dir)
            if sync_results:
                for filename, (election, new_names) in sync_results.items():
                    print(f"  {election.name}: loaded")
                    if new_names:
                        print(f"    ⚠  {len(new_names)} unrecognized contest name(s)")
            else:
                print("  No new CSV files found.")

    print(f"\nDone. Run sync_sources.py to load future elections.")


if __name__ == "__main__":
    excel_path  = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXCEL
    sources_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SOURCES_DIR
    main(excel_path, sources_dir)
