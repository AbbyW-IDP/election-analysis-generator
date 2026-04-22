"""
sync_sources.py
---------------
Scan elections.toml and load any elections whose source CSV hasn't been
loaded yet. Database entries are never removed when a source is deleted.

Usage:
    uv run python sync_sources.py [sources_dir] [config_path]
"""

import sys
from pathlib import Path

from dupage_elections.db import ElectionDatabase, DEFAULT_DB_PATH
from dupage_elections.loader import ElectionLoader, DEFAULT_SOURCES_DIR, DEFAULT_CONFIG_PATH


def main(
    sources_dir: Path = DEFAULT_SOURCES_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with ElectionDatabase(db_path) as db:
        loader = ElectionLoader(db)

        print(f"Scanning {config_path} for new elections...")
        results = loader.sync(sources_dir=sources_dir, config_path=config_path)

        if not results:
            print("No new elections found.")
            return

        any_flags = False
        for filename, (election, new_names) in results.items():
            print(f"\n  {election.name} ({filename}): loaded successfully")
            if new_names:
                any_flags = True
                print(f"  ⚠  {len(new_names)} unrecognized contest name(s):")
                for name in new_names:
                    print(f"    {name}")

        if any_flags:
            print("\nRun: uv run python review_flags.py")
            print("  or: uv run python export_flags.py  (for large batches)")


if __name__ == "__main__":
    sources_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCES_DIR
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONFIG_PATH
    main(sources_dir, config_path)
