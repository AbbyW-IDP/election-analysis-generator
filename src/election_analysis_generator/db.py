"""
db.py
-----
ElectionDatabase: owns the SQLite connection and all database operations.

This module is the single point of contact between the rest of the codebase
and the SQLite database. No other module executes SQL directly — everything
goes through ElectionDatabase methods.

The database has two kinds of tables:

  Data tables — store election results:
    elections                 One row per election event (e.g. "2022 General Primary")
    contests                  One row per unique contest (e.g. "FOR ATTORNEY GENERAL")
    candidates                One row per candidate per contest per election (county-wide totals)
    candidate_precinct_results  One row per candidate per contest per precinct per election

  Bookkeeping tables — support the load and review workflow:
    contest_names             Registry of all known normalized contest names
    contest_name_flags        Names from new sources that didn't match any known name
    contest_name_overrides    Manual mappings: raw name → canonical normalized name
    loaded_sources            Tracks which source files have already been loaded

For a full description of each table and column, see README.md.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from .models import Election
from .normalize import (
    normalize_contest_name,
    normalize_party,
)

DEFAULT_DB_PATH = Path("elections.db")

_SCHEMA = """
    -- One row per election event (e.g. "2022 General Primary")
    CREATE TABLE IF NOT EXISTS elections (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        name                 TEXT NOT NULL UNIQUE,
        year                 INTEGER NOT NULL,
        election_date        TEXT,
        results_last_updated TEXT,
        source_file          TEXT NOT NULL UNIQUE,
        category             TEXT NOT NULL DEFAULT '',
        election_type        TEXT NOT NULL DEFAULT '',
        ballots_cast         INTEGER,
        registered_voters    INTEGER
    );

    -- One row per unique normalized contest name
    CREATE TABLE IF NOT EXISTS contests (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_name   TEXT NOT NULL UNIQUE,
        is_legislation INTEGER NOT NULL DEFAULT 0  -- 0=false, 1=true
    );

    -- One row per candidate/row in a source CSV
    CREATE TABLE IF NOT EXISTS candidates (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id          INTEGER NOT NULL REFERENCES contests(id),
        election_id         INTEGER NOT NULL REFERENCES elections(id),
        line_number         INTEGER,
        contest_name_raw    TEXT NOT NULL,
        contest_name        TEXT NOT NULL,
        election_name       TEXT NOT NULL,
        year                INTEGER NOT NULL,
        choice_name         TEXT,
        party               TEXT,
        total_votes         REAL,
        percent_of_votes    REAL,
        registered_voters   REAL,
        ballots_cast        REAL,
        num_precinct_total  REAL,
        num_precinct_rptg   REAL,
        over_votes          REAL,
        under_votes         REAL
    );

    -- Registry of known normalized contest names (used for flagging)
    CREATE TABLE IF NOT EXISTS contest_names (
        contest_name        TEXT PRIMARY KEY,
        first_seen_year     INTEGER NOT NULL
    );

    -- Contest names from new sources that didn't match any known name
    CREATE TABLE IF NOT EXISTS contest_name_flags (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        year                INTEGER NOT NULL,
        contest_name_raw    TEXT NOT NULL,
        contest_name        TEXT NOT NULL,
        resolved            INTEGER NOT NULL DEFAULT 0,
        flagged_at          TEXT DEFAULT (datetime('now'))
    );

    -- Manual overrides: raw name -> canonical normalized name
    CREATE TABLE IF NOT EXISTS contest_name_overrides (
        contest_name_raw    TEXT PRIMARY KEY,
        contest_name        TEXT NOT NULL,
        note                TEXT
    );

    -- Registry of source files that have been loaded
    CREATE TABLE IF NOT EXISTS loaded_sources (
        filename            TEXT PRIMARY KEY,
        election_id         INTEGER REFERENCES elections(id),
        loaded_at           TEXT DEFAULT (datetime('now'))
    );

    -- Precinct-level results from detail Excel files
    CREATE TABLE IF NOT EXISTS candidate_precinct_results (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        election_id         INTEGER NOT NULL REFERENCES elections(id),
        contest_id          INTEGER NOT NULL REFERENCES contests(id),
        contest_name_raw    TEXT NOT NULL,
        choice_name         TEXT NOT NULL,
        precinct            TEXT NOT NULL,
        registered_voters   INTEGER,
        early_votes         INTEGER,
        vote_by_mail        INTEGER,
        polling             INTEGER,
        provisional         INTEGER,
        total_votes         INTEGER NOT NULL,
        UNIQUE (election_id, contest_id, choice_name, precinct)
    );

    CREATE INDEX IF NOT EXISTS idx_precinct_results_election
        ON candidate_precinct_results (election_id);

    CREATE INDEX IF NOT EXISTS idx_precinct_results_contest
        ON candidate_precinct_results (election_id, contest_id);

    CREATE INDEX IF NOT EXISTS idx_precinct_results_precinct
        ON candidate_precinct_results (election_id, precinct);
"""


def _placeholders(n: int) -> str:
    """Return a comma-separated string of n '?' placeholders for use in SQL IN clauses."""
    return ",".join("?" * n)


class ElectionDatabase:
    """
    Manages the elections SQLite database.

    This class is the only place in the codebase that talks to SQLite directly.
    It handles three concerns:

      1. Schema — creates all tables and indexes on first run (idempotent, so
         safe to call on an existing database).

      2. Writes — inserting elections, candidates, precinct results, contest
         registrations, flags, and overrides.

      3. Reads — retrieving elections by name or id, querying flags, and a
         general-purpose query() method used by ElectionAnalyzer.

    The database file is created automatically if it doesn't exist. Pass
    ":memory:" as db_path to create a temporary in-memory database (used in
    tests).

    Foreign key enforcement is enabled on every connection, so inserting a
    candidate row that references a non-existent election or contest will raise
    an IntegrityError rather than silently storing a broken reference.

    Typical usage via context manager (ensures the connection is closed):

        with ElectionDatabase() as db:
            db.insert_election(election, df)

    Or manually:

        db = ElectionDatabase()
        db.insert_election(election, df)
        db.close()
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        """Create all tables and indexes if they don't already exist.

        Called automatically by __init__, so the database is always ready to
        use immediately after construction. Safe to call on an existing
        database — every statement in _SCHEMA uses CREATE TABLE/INDEX IF NOT
        EXISTS, so already-created objects are silently skipped rather than
        raising an error.

        This means adding a new table to _SCHEMA (as was done for
        candidate_precinct_results) takes effect automatically the next time
        sync-sources runs against an existing database, with no separate
        migration step needed.
        """
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Elections
    #
    # An "election" is a single event — e.g. the 2026 General Primary.
    # Each election has one source CSV (summary totals) and optionally one
    # detail Excel file (precinct-level breakdown). insert_election() handles
    # the summary CSV path; insert_precinct_results() handles the detail path.
    # ------------------------------------------------------------------

    def insert_election(
        self, election: Election, df: pd.DataFrame
    ) -> tuple[Election, list[str]]:
        """
        Insert an Election and all its candidates from a normalized DataFrame.

        This is the main entry point called by ElectionLoader when processing
        a summary CSV. It performs four steps in a single transaction:

          1. Inserts the election row into the elections table and captures
             the auto-assigned integer id.
          2. Normalizes the raw contest and party names in df (applying any
             manual overrides first, then the standard normalization rules).
          3. Upserts each unique contest into the contests table and flags any
             contest names not previously seen in this database.
          4. Inserts one candidate row per row in df into the candidates table.

        The ballots_cast and registered_voters on the elections table are
        election-wide figures that come from elections.toml (via the Election
        object). These may differ from the per-contest figures stored on each
        candidate row, which come directly from the CSV. Both are preserved.

        Args:
            election:   An Election dataclass (id should be None — it will be
                        assigned by the database and returned).
            df:         A DataFrame of candidate rows for this election, as
                        produced by ElectionLoader. Must contain at minimum:
                        contest_name_raw, choice_name, party, total_votes.

        Returns:
            A tuple of:
              - The same Election object with its new database id populated.
              - A sorted list of normalized contest names that were not
                previously in the contest_names registry and were therefore
                flagged for review. Empty list if all names were recognized.
        """
        cur = self._conn.execute(
            """
            INSERT INTO elections
                (name, year, election_date, results_last_updated,
                 source_file, category, election_type,
                 ballots_cast, registered_voters)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                election.name,
                election.year,
                election.election_date.isoformat() if election.election_date else None,
                election.results_last_updated.isoformat()
                if election.results_last_updated
                else None,
                election.source_file,
                election.category,
                election.election_type,
                election.ballots_cast,
                election.registered_voters,
            ),
        )
        election_id = cur.lastrowid
        if election_id is None:
            raise RuntimeError("INSERT INTO elections failed to return a row id")
        election = Election(
            id=election_id,
            name=election.name,
            year=election.year,
            election_date=election.election_date,
            results_last_updated=election.results_last_updated,
            source_file=election.source_file,
            category=election.category,
            election_type=election.election_type,
            ballots_cast=election.ballots_cast,
            registered_voters=election.registered_voters,
        )

        known = self.get_known_contest_names()
        normalized_df = self._normalize_df(df, self.get_overrides())
        new_names = self._upsert_contests(normalized_df, election.year, known)
        self._insert_candidates(
            normalized_df, election_id, election.name, election.year
        )

        self._conn.commit()
        return election, new_names

    def _normalize_df(
        self, df: pd.DataFrame, overrides: dict[str, str]
    ) -> pd.DataFrame:
        """
        Apply contest name and party normalization to a raw candidates DataFrame.

        Contest name normalization converts raw names from the CSV (which vary
        across years and include noise like party suffixes and parentheticals)
        into a consistent canonical form. For example:
            "FOR ATTORNEY GENERAL - D*"  →  "FOR ATTORNEY GENERAL"
            "United States Senator"      →  "UNITED STATES SENATOR"

        If a raw name has a manual override entry in contest_name_overrides
        (because it was resolved via the flags review workflow), the override
        takes precedence over the automatic normalization rules.

        Party normalization standardizes the raw party strings from the CSV
        into short codes: "DEM", "REP", "GP", "WC", etc.

        Returns a new DataFrame (the original is not modified) with two
        columns added/replaced: contest_name (normalized) and party (normalized).
        """
        df = df.copy()
        df["contest_name_raw"] = df["contest_name_raw"].astype(str)
        df["contest_name"] = df["contest_name_raw"].apply(
            lambda r: overrides[r] if r in overrides else normalize_contest_name(r)
        )
        df["party"] = df["party"].apply(normalize_party)
        return df

    def _upsert_contests(
        self,
        df: pd.DataFrame,
        year: int,
        known: set[str],
    ) -> list[str]:
        """
        Register all unique contest names from df, flagging any that are new.

        For each unique normalized contest name in df, this method does three
        things:

          1. Inserts the contest into the contests table if it isn't already
             there (INSERT OR IGNORE, so existing rows are untouched).

          2. Registers the name in contest_names (the "known names" registry)
             with the year it was first seen. This registry is what future
             loads check against to decide whether a name is new.

          3. If the name wasn't in the known set passed in, adds it to the
             returned list and writes a flag row to contest_name_flags so a
             human can review it.

        The known set is captured once at the start of insert_election() so
        that all contest names from the same load are evaluated against the
        same baseline — names added during this load don't suppress flags for
        other new names in the same file.

        Returns a sorted list of newly flagged contest names (those not in
        known). Empty list if all names were already registered.
        """
        new_names = []

        for contest_name in df["contest_name"].unique():
            contest_rows: pd.DataFrame = df[df["contest_name"] == contest_name]  # type: ignore[assignment]
            self._upsert_contest(contest_name, contest_rows)
            self._conn.execute(
                "INSERT OR IGNORE INTO contest_names (contest_name, first_seen_year) VALUES (?,?)",
                (contest_name, year),
            )
            if contest_name not in known:
                new_names.append(contest_name)

        if new_names:
            flagged_rows: pd.DataFrame = df[df["contest_name"].isin(new_names)]  # type: ignore[assignment]
            self._write_flags(flagged_rows, year)

        return sorted(new_names)

    def _insert_candidates(
        self,
        df: pd.DataFrame,
        election_id: int,
        election_name: str,
        year: int,
    ) -> None:
        """Insert all candidate rows from df into the candidates table.

        Each row in df becomes one row in candidates, representing a single
        candidate's county-wide total for one contest in one election. This
        is the summary grain — one number per candidate per contest, not
        broken down by precinct.

        The contest_id FK is resolved here by looking up each row's normalized
        contest_name in the contests table. This lookup is safe because
        _upsert_contests() always runs before this method within the same
        insert_election() transaction, guaranteeing every contest_name in df
        already exists in contests.

        election_name and year are denormalized onto each candidate row (they
        could be derived via a JOIN to elections) to make analysis queries
        simpler and faster — ElectionAnalyzer queries candidates directly
        without always needing to join elections.
        """
        for _, row in df.iterrows():
            contest_id = self._conn.execute(
                "SELECT id FROM contests WHERE contest_name = ?",
                (row["contest_name"],),
            ).fetchone()["id"]

            self._conn.execute(
                """
                INSERT INTO candidates
                    (contest_id, election_id, line_number, contest_name_raw,
                     contest_name, election_name, year,
                     choice_name, party, total_votes, percent_of_votes,
                     registered_voters, ballots_cast,
                     num_precinct_total, num_precinct_rptg, over_votes, under_votes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contest_id,
                    election_id,
                    int(row["line_number"])  # type: ignore[arg-type]
                    if row.get("line_number") is not None
                    and not pd.isna(row.get("line_number"))  # type: ignore[arg-type]
                    else None,
                    row["contest_name_raw"],
                    row["contest_name"],
                    election_name,
                    year,
                    row.get("choice_name"),
                    row.get("party"),
                    row.get("total_votes"),
                    row.get("percent_of_votes"),
                    row.get("registered_voters"),
                    row.get("ballots_cast"),
                    row.get("num_precinct_total"),
                    row.get("num_precinct_rptg"),
                    row.get("over_votes"),
                    row.get("under_votes"),
                ),
            )

    def _upsert_contest(self, contest_name: str, rows: pd.DataFrame) -> None:
        """Insert a contest into the contests table if it doesn't already exist.

        Contests are identified by their normalized name (the primary key), so
        the same contest across multiple elections — e.g. "FOR ATTORNEY
        GENERAL" in 2022 and 2026 — maps to the same contests row. This is
        what makes cross-election comparisons possible in ElectionAnalyzer.

        The is_legislation flag is inferred from the candidate rows: if any
        row for this contest has a non-empty party value after normalization,
        it's treated as a partisan race (is_legislation=0). If no rows have a
        party, it's treated as a ballot measure (is_legislation=1). This can
        be overridden manually via set_contest_legislation_flag() if the
        inference is wrong.
        """
        existing = self._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?", (contest_name,)
        ).fetchone()
        if existing:
            return

        # Issue #1: normalize_party has already run, so check for non-null,
        # non-empty string values rather than raw truthiness. A blank or
        # whitespace-only party (e.g. from an empty CSV cell) must not be
        # treated as a valid partisan affiliation.
        has_party: bool = (
            bool(rows["party"].apply(lambda p: isinstance(p, str) and p.strip() != "").any())
            if "party" in rows.columns
            else False
        )
        is_legislation = 0 if has_party else 1

        self._conn.execute(
            "INSERT OR IGNORE INTO contests (contest_name, is_legislation) VALUES (?,?)",
            (contest_name, is_legislation),
        )

    def set_contest_legislation_flag(
        self, contest_name: str, is_legislation: bool
    ) -> None:
        """Manually override the is_legislation flag for a contest.

        The flag is normally inferred automatically when the contest is first
        inserted — contests with no party affiliation are marked as legislation
        (ballot measures). Use this method to correct mis-inferences, e.g. if
        a non-partisan race was incorrectly flagged as legislation, or vice
        versa.

        ElectionAnalyzer filters out is_legislation=1 contests when computing
        partisan comparisons, so this flag affects which contests appear in
        analysis output.
        """
        self._conn.execute(
            "UPDATE contests SET is_legislation = ? WHERE contest_name = ?",
            (1 if is_legislation else 0, contest_name),
        )
        self._conn.commit()

    def get_election_by_name(self, name: str) -> Election | None:
        """Retrieve an Election by its display name (e.g. "2026 General Primary").

        Returns None if no election with that name exists. Used by
        ElectionAnalyzer when an election is specified as a string.
        """
        row = self._conn.execute(
            "SELECT * FROM elections WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_election(row) if row else None

    def get_election_by_id(self, election_id: int) -> Election | None:
        """Retrieve an Election by its integer database id.

        Returns None if no election with that id exists. Used by
        ElectionAnalyzer when an election is specified as an id.
        """
        row = self._conn.execute(
            "SELECT * FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        return self._row_to_election(row) if row else None

    def get_all_elections(self) -> list[Election]:
        """Return all elections in the database, ordered by year then date.

        Used by ElectionAnalyzer.list_elections() and by the CLI to display
        what has been loaded.
        """
        rows = self._conn.execute(
            "SELECT * FROM elections ORDER BY year, election_date"
        ).fetchall()
        return [self._row_to_election(r) for r in rows]

    def _row_to_election(self, row) -> Election:
        """Convert a sqlite3.Row from the elections table into an Election dataclass.

        Handles the date columns, which are stored as ISO 8601 strings in
        SQLite and need to be parsed back into Python date objects. Both date
        fields are nullable, so the conversion is conditional.
        """
        return Election(
            id=row["id"],
            name=row["name"],
            year=row["year"],
            election_date=date.fromisoformat(row["election_date"])
            if row["election_date"]
            else None,
            results_last_updated=date.fromisoformat(row["results_last_updated"])
            if row["results_last_updated"]
            else None,
            source_file=row["source_file"],
            category=row["category"],
            election_type=row["election_type"],
            ballots_cast=row["ballots_cast"],
            registered_voters=row["registered_voters"],
        )

    # ------------------------------------------------------------------
    # Source file registry
    #
    # loaded_sources tracks which source files have already been processed.
    # ElectionLoader checks is_source_loaded() before attempting to load a
    # file, and calls register_source() after a successful load. This makes
    # sync-sources idempotent — running it multiple times will not re-load
    # files that are already in the database.
    #
    # The filename stored here is the basename from elections.toml (e.g.
    # "2026-general-primary-2026-04-07.csv"), not a full filesystem path.
    # ------------------------------------------------------------------

    def is_source_loaded(self, filename: str) -> bool:
        """Return True if this source file has already been loaded.

        Called by ElectionLoader before processing a file to avoid loading
        the same data twice. The filename must match exactly what was passed
        to register_source() — typically the basename from elections.toml.
        """
        row = self._conn.execute(
            "SELECT 1 FROM loaded_sources WHERE filename = ?", (filename,)
        ).fetchone()
        return row is not None

    def register_source(self, filename: str, election_id: int) -> None:
        """Mark a source file as loaded, linked to the given election.

        Called by ElectionLoader after a successful load so that subsequent
        sync-sources runs skip this file. INSERT OR IGNORE means calling this
        twice for the same filename is safe.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO loaded_sources (filename, election_id) VALUES (?,?)",
            (filename, election_id),
        )
        self._conn.commit()

    def get_loaded_sources(self) -> list[dict]:
        """Return all loaded source records as a list of dicts.

        Each dict has keys: filename, election_id, loaded_at. Ordered by
        load time. Used by the CLI to display what has been loaded and when.
        """
        rows = self._conn.execute(
            "SELECT filename, election_id, loaded_at FROM loaded_sources ORDER BY loaded_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Contest name registry
    #
    # contest_names is a flat list of every normalized contest name that has
    # been seen and accepted across all elections in this database. It is the
    # reference set used to detect new/unknown names when a new election is
    # loaded.
    #
    # The distinction between contest_names and contests:
    #   contests        — one row per contest, with metadata (is_legislation).
    #                     Used for analysis and FK references from candidates.
    #   contest_names   — one row per known name, with first_seen_year.
    #                     Used only for new-name detection at load time.
    #
    # They stay in sync because _upsert_contests() writes to both tables
    # together inside the same transaction.
    # ------------------------------------------------------------------

    def get_known_contest_names(self) -> set[str]:
        """Return the set of all normalized contest names in the registry.

        Called once at the start of insert_election() to capture the baseline
        of known names before the new election is loaded. Any contest name in
        the new file that isn't in this set will be flagged for review.
        """
        rows = self._conn.execute("SELECT contest_name FROM contest_names").fetchall()
        return {r[0] for r in rows}

    def register_contest_name(self, name: str, year: int) -> None:
        """Add a normalized contest name to the registry, if not already present.

        Called by _upsert_contests() during a load, and also directly by
        conftest.py's seed_election() in tests to pre-register names so they
        don't get flagged as unknown. INSERT OR IGNORE means calling this for
        an already-known name is safe.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO contest_names (contest_name, first_seen_year) VALUES (?,?)",
            (name, year),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Overrides
    #
    # contest_name_overrides is a manual mapping table: raw name (as it
    # appears in a source file) → canonical normalized name (as stored in
    # contests and contest_names). An override is added when a flag is
    # resolved with status "mapped" — meaning the raw name from a new
    # source should be treated as the same contest as an existing one,
    # bypassing the automatic normalization rules.
    #
    # On every subsequent load, _normalize_df() checks this table first
    # before applying normalization, so a renamed contest only needs to be
    # resolved once.
    # ------------------------------------------------------------------

    def get_overrides(self) -> dict[str, str]:
        """Return all manual overrides as a {raw_name: canonical_name} dict.

        Loaded once at the start of each insert_election() call and passed
        to _normalize_df() so the override lookup happens in Python rather
        than per-row in SQL.
        """
        rows = self._conn.execute(
            "SELECT contest_name_raw, contest_name FROM contest_name_overrides"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def add_override(
        self, raw_name: str, canonical_name: str, note: str | None = None
    ) -> None:
        """Add or replace a manual override mapping.

        Called by import_flags() in flags.py when a flag is resolved with
        status "mapped". The note field is optional free text for explaining
        why the mapping was made (e.g. "renamed between 2022 and 2026").

        INSERT OR REPLACE means calling this for an existing raw_name updates
        the canonical target rather than raising an error.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO contest_name_overrides (contest_name_raw, contest_name, note) VALUES (?,?,?)",
            (raw_name, canonical_name, note),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Flags
    #
    # When a new election is loaded, any normalized contest name that isn't
    # already in contest_names is written to contest_name_flags with
    # resolved=0. This signals that a human needs to decide whether to:
    #   - Accept it as a genuinely new contest (resolved via export/import
    #     flags or review-flags)
    #   - Map it to an existing contest (adds an override)
    #   - Ignore it (e.g. a ballot measure not being tracked)
    #
    # Flags do not block the load — the contest and its candidates are
    # stored regardless. Flags are purely a review prompt.
    # ------------------------------------------------------------------

    def get_unresolved_flags(self) -> list[dict]:
        """Return all flags that have not yet been resolved.

        Each dict has keys: id, year, contest_name_raw, contest_name.
        Used by review_flags() (interactive terminal review) and
        export_flags() (spreadsheet export) in flags.py.
        """
        rows = self._conn.execute("""
            SELECT id, year, contest_name_raw, contest_name
            FROM contest_name_flags
            WHERE resolved = 0
            ORDER BY year, contest_name
        """).fetchall()
        return [dict(r) for r in rows]

    def resolve_flag(self, flag_id: int) -> None:
        """Mark a flag as resolved (resolved=1).

        Called by import_flags() and review_flags() after a decision has been
        recorded. Resolved flags no longer appear in get_unresolved_flags(),
        but the rows remain in the table as a permanent audit trail.
        """
        self._conn.execute(
            "UPDATE contest_name_flags SET resolved = 1 WHERE id = ?", (flag_id,)
        )
        self._conn.commit()

    def _write_flags(self, df: pd.DataFrame, year: int) -> None:
        """Insert flag rows for all unique contest names in df.

        Called internally by _upsert_contests() for the subset of names that
        weren't in the known set. Each unique (contest_name_raw, contest_name)
        pair becomes one flag row. The guard on df.empty means callers don't
        need to check before calling — writing zero flags is a no-op.
        """
        if df.empty:
            return
        flag_df = df[["contest_name_raw", "contest_name"]].drop_duplicates().copy()
        flag_df["year"] = year
        flag_rows = flag_df[["year", "contest_name_raw", "contest_name"]].itertuples(  # type: ignore[union-attr]
            index=False
        )
        self._conn.executemany(
            "INSERT INTO contest_name_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            flag_rows,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Precinct-level results
    #
    # candidate_precinct_results stores the geographic breakdown of votes
    # from detail Excel files. Where the candidates table has one row per
    # candidate per contest per election (county-wide total), this table has
    # one row per candidate per contest per precinct per election.
    #
    # The two tables are populated from different source files and never
    # interfere with each other:
    #   Summary CSV    → candidates          (loaded by ElectionLoader)
    #   Detail Excel   → candidate_precinct_results  (loaded by load_detail_excel)
    #
    # Summing total_votes by (election_id, contest_id, choice_name) in this
    # table should equal total_votes in candidates for the same combination.
    # The cross-check query in the schema notes can verify this after a load.
    # ------------------------------------------------------------------

    def insert_precinct_results(self, rows: list[dict]) -> int:
        """Insert precinct-level result rows, skipping duplicates.

        Each dict in *rows* must have the keys:
            election_id, contest_id, contest_name_raw, choice_name,
            precinct, registered_voters, early_votes, vote_by_mail,
            polling, provisional, total_votes

        contest_id must be the integer primary key from the contests table,
        not the normalized name string.

        Returns the number of rows actually inserted. Duplicates are silently
        skipped via INSERT OR IGNORE, so the count may be less than len(rows).

        Raises:
            sqlite3.IntegrityError  – if election_id or contest_id FK is
                                      missing (i.e. the election/contest was
                                      not registered before calling this).
        """
        sql = """
            INSERT OR IGNORE INTO candidate_precinct_results (
                election_id,
                contest_id,
                contest_name_raw,
                choice_name,
                precinct,
                registered_voters,
                early_votes,
                vote_by_mail,
                polling,
                provisional,
                total_votes
            ) VALUES (
                :election_id,
                :contest_id,
                :contest_name_raw,
                :choice_name,
                :precinct,
                :registered_voters,
                :early_votes,
                :vote_by_mail,
                :polling,
                :provisional,
                :total_votes
            )
        """
        cursor = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Read access (for analysis)
    #
    # ElectionAnalyzer uses query() for all its reads rather than having
    # dedicated getter methods for each analysis shape. This keeps db.py
    # focused on data integrity and lets analysis logic live entirely in
    # analysis.py.
    # ------------------------------------------------------------------

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Execute a SELECT and return results as a DataFrame.

        The general-purpose read method used by ElectionAnalyzer. Accepts any
        valid SELECT statement and optional positional parameters (passed as a
        list, matched to ? placeholders in the SQL).

        params is handled carefully: passing None and passing [] behave
        differently in some SQLite drivers, so None means "no parameters"
        and skips the params argument entirely.

        Example:
            df = db.query(
                "SELECT * FROM candidates WHERE election_id = ?",
                params=[election_id]
            )
        """
        if params is not None:
            return pd.read_sql(sql, self._conn, params=params)
        return pd.read_sql(sql, self._conn)
