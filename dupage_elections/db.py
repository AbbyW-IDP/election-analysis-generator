"""
db.py
-----
ElectionDatabase: owns the SQLite connection and all database operations.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from dupage_elections.models import Election, Contest, Candidate
from dupage_elections.normalize import normalize_contest_name, normalize_party

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
        choice_name         TEXT,
        party               TEXT,
        total_votes         REAL,
        percent_of_votes    REAL,
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
"""


class ElectionDatabase:
    """
    Manages the elections SQLite database.

    Usage:
        with ElectionDatabase() as db:
            db.insert_election(election, df)
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
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Elections
    # ------------------------------------------------------------------

    def insert_election(self, election: Election, df: pd.DataFrame) -> Election:
        """
        Insert an Election and all its candidates from a normalized DataFrame.
        Derives ballots_cast and registered_voters from the DataFrame.
        Returns the Election with its database id populated.
        """
        overrides = self.get_overrides()

        # Derive counts from CSV data
        ballots_cast = int(df["ballots_cast"].max()) if "ballots_cast" in df.columns else None
        registered_voters = int(df["registered_voters"].max()) if "registered_voters" in df.columns else None

        cur = self._conn.execute(
            """
            INSERT INTO elections
                (name, year, election_date, results_last_updated,
                 source_file, ballots_cast, registered_voters)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                election.name,
                election.year,
                election.election_date.isoformat() if election.election_date else None,
                election.results_last_updated.isoformat() if election.results_last_updated else None,
                election.source_file,
                ballots_cast,
                registered_voters,
            ),
        )
        election_id = cur.lastrowid
        election = Election(
            id=election_id,
            name=election.name,
            year=election.year,
            election_date=election.election_date,
            results_last_updated=election.results_last_updated,
            source_file=election.source_file,
            ballots_cast=ballots_cast,
            registered_voters=registered_voters,
        )

        # Normalize and insert all candidates
        known = self.get_known_contest_names()
        new_names = []

        df = df.copy()
        df["contest_name_raw"] = df["contest_name_raw"].astype(str)
        df["contest_name"] = df["contest_name_raw"].apply(
            lambda r: overrides[r] if r in overrides else normalize_contest_name(r)
        )
        df["party"] = df["party"].apply(normalize_party)

        # Detect new contest names for flagging
        for name in df["contest_name"].unique():
            if name not in known:
                new_names.append(name)
            self._upsert_contest(name, df[df["contest_name"] == name])
            self._conn.execute(
                "INSERT OR IGNORE INTO contest_names (contest_name, first_seen_year) VALUES (?,?)",
                (name, election.year),
            )

        if new_names:
            self._write_flags(df[df["contest_name"].isin(new_names)], election.year)

        # Insert candidate rows
        for _, row in df.iterrows():
            contest_id = self._conn.execute(
                "SELECT id FROM contests WHERE contest_name = ?",
                (row["contest_name"],),
            ).fetchone()["id"]

            self._conn.execute(
                """
                INSERT INTO candidates
                    (contest_id, election_id, line_number, contest_name_raw,
                     choice_name, party, total_votes, percent_of_votes,
                     num_precinct_total, num_precinct_rptg, over_votes, under_votes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contest_id,
                    election_id,
                    int(row["line_number"]) if row.get("line_number") is not None and not pd.isna(row.get("line_number")) else None,
                    row["contest_name_raw"],
                    row.get("choice_name"),
                    row.get("party"),
                    row.get("total_votes"),
                    row.get("percent_of_votes"),
                    row.get("num_precinct_total"),
                    row.get("num_precinct_rptg"),
                    row.get("over_votes"),
                    row.get("under_votes"),
                ),
            )

        self._conn.commit()
        return election

    def _upsert_contest(self, contest_name: str, rows: pd.DataFrame) -> None:
        """Insert a contest if it doesn't exist. Infer is_legislation from party data."""
        existing = self._conn.execute(
            "SELECT id FROM contests WHERE contest_name = ?", (contest_name,)
        ).fetchone()
        if existing:
            return

        # Infer legislation: no non-null party values means no partisan candidates
        has_party = rows["party"].notna().any() if "party" in rows.columns else False
        is_legislation = 0 if has_party else 1

        self._conn.execute(
            "INSERT OR IGNORE INTO contests (contest_name, is_legislation) VALUES (?,?)",
            (contest_name, is_legislation),
        )

    def set_contest_legislation_flag(self, contest_name: str, is_legislation: bool) -> None:
        """Manually override the is_legislation flag for a contest."""
        self._conn.execute(
            "UPDATE contests SET is_legislation = ? WHERE contest_name = ?",
            (1 if is_legislation else 0, contest_name),
        )
        self._conn.commit()

    def get_election_by_name(self, name: str) -> Election | None:
        """Retrieve an Election by name."""
        row = self._conn.execute(
            "SELECT * FROM elections WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_election(row) if row else None

    def get_election_by_id(self, election_id: int) -> Election | None:
        """Retrieve an Election by id."""
        row = self._conn.execute(
            "SELECT * FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        return self._row_to_election(row) if row else None

    def get_all_elections(self) -> list[Election]:
        """Return all elections ordered by date."""
        rows = self._conn.execute(
            "SELECT * FROM elections ORDER BY year, election_date"
        ).fetchall()
        return [self._row_to_election(r) for r in rows]

    def _row_to_election(self, row) -> Election:
        return Election(
            id=row["id"],
            name=row["name"],
            year=row["year"],
            election_date=date.fromisoformat(row["election_date"]) if row["election_date"] else None,
            results_last_updated=date.fromisoformat(row["results_last_updated"]) if row["results_last_updated"] else None,
            source_file=row["source_file"],
            ballots_cast=row["ballots_cast"],
            registered_voters=row["registered_voters"],
        )

    # ------------------------------------------------------------------
    # Source file registry
    # ------------------------------------------------------------------

    def is_source_loaded(self, filename: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM loaded_sources WHERE filename = ?", (filename,)
        ).fetchone()
        return row is not None

    def register_source(self, filename: str, election_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO loaded_sources (filename, election_id) VALUES (?,?)",
            (filename, election_id),
        )
        self._conn.commit()

    def get_loaded_sources(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT filename, election_id, loaded_at FROM loaded_sources ORDER BY loaded_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Contest name registry
    # ------------------------------------------------------------------

    def get_known_contest_names(self) -> set[str]:
        rows = self._conn.execute("SELECT contest_name FROM contest_names").fetchall()
        return {r[0] for r in rows}

    def register_contest_name(self, name: str, year: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO contest_names (contest_name, first_seen_year) VALUES (?,?)",
            (name, year),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def get_overrides(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT contest_name_raw, contest_name FROM contest_name_overrides"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def add_override(self, raw_name: str, canonical_name: str, note: str | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO contest_name_overrides (contest_name_raw, contest_name, note) VALUES (?,?,?)",
            (raw_name, canonical_name, note),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def get_unresolved_flags(self) -> list[dict]:
        rows = self._conn.execute("""
            SELECT id, year, contest_name_raw, contest_name
            FROM contest_name_flags
            WHERE resolved = 0
            ORDER BY year, contest_name
        """).fetchall()
        return [dict(r) for r in rows]

    def resolve_flag(self, flag_id: int) -> None:
        self._conn.execute(
            "UPDATE contest_name_flags SET resolved = 1 WHERE id = ?", (flag_id,)
        )
        self._conn.commit()

    def _write_flags(self, df: pd.DataFrame, year: int) -> None:
        flag_df = df[["contest_name_raw", "contest_name"]].drop_duplicates().copy()
        flag_df["year"] = year
        flag_rows = flag_df[["year", "contest_name_raw", "contest_name"]].itertuples(index=False)
        self._conn.executemany(
            "INSERT INTO contest_name_flags (year, contest_name_raw, contest_name) VALUES (?,?,?)",
            flag_rows,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read access (for analysis)
    # ------------------------------------------------------------------

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Execute a SELECT and return results as a DataFrame."""
        return pd.read_sql(sql, self._conn, params=params or [])
