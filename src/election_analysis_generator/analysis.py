"""
analysis.py
-----------
ElectionAnalyzer: a library of analyses that can be run against any
combination of elections in the database.

Analyses operate on election names or IDs and always return DataFrames.
Contests are matched across elections by normalized contest name.
"""

from datetime import date

import pandas as pd

from .db import ElectionDatabase, _placeholders
from .models import Election


def _resolve_elections(
    db: ElectionDatabase,
    elections: list[str | int | Election],
) -> list[Election]:
    """
    Resolve a list of election identifiers (name, id, or Election object)
    to a list of Election objects. Raises ValueError for any not found.
    """
    resolved = []
    for e in elections:
        if isinstance(e, Election):
            resolved.append(e)
        elif isinstance(e, str):
            obj = db.get_election_by_name(e)
            if obj is None:
                raise ValueError(f"Election not found: {e!r}")
            resolved.append(obj)
        elif isinstance(e, int):
            obj = db.get_election_by_id(e)
            if obj is None:
                raise ValueError(f"Election not found with id: {e}")
            resolved.append(obj)
        else:
            raise TypeError(
                f"Expected election name, id, or Election object; got {type(e)}"
            )
    return resolved


class ElectionAnalyzer:
    """
    A library of analyses over election data.

    Elections can be specified by name (str), database id (int), or
    Election object — all analysis methods accept any mix of these.

    Usage:
        analyzer = ElectionAnalyzer(db)

        # By name
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )

        # By id
        result = analyzer.party_share(1, 2, 3)

        # List all elections
        elections = analyzer.list_elections()
    """

    def __init__(self, db: ElectionDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Election listing
    # ------------------------------------------------------------------

    def list_elections(self) -> pd.DataFrame:
        """Return a summary of all elections in the database."""
        return self._db.query("""
            SELECT id, name, year, election_date, category, election_type,
                   results_last_updated, ballots_cast, registered_voters,
                   source_file
            FROM elections
            ORDER BY year, election_date
        """)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _get_party_totals(
        self,
        election_ids: list[int],
        parties: tuple[str, ...] = ("DEM", "REP"),
    ) -> pd.DataFrame:
        """
        Aggregate total votes per contest × party × election.
        Excludes legislation contests.
        """
        return self._db.query(
            f"""
            SELECT
                e.id        AS election_id,
                e.name      AS election_name,
                e.year,
                e.election_date,
                co.contest_name,
                ca.party,
                SUM(ca.total_votes) AS party_total
            FROM candidates ca
            JOIN contests  co ON ca.contest_id  = co.id
            JOIN elections e  ON ca.election_id = e.id
            WHERE e.id IN ({_placeholders(len(election_ids))})
              AND ca.party IN ({_placeholders(len(parties))})
              AND co.is_legislation = 0
            GROUP BY e.id, co.contest_name, ca.party
            """,  # nosec B608 - placeholders only, values passed as parameters
            list(election_ids) + list(parties),
        )

    def _comparable_contests(
        self,
        totals: pd.DataFrame,
        election_ids: list[int],
        parties: tuple[str, ...] = ("DEM", "REP"),
    ) -> set[str]:
        """
        Return contest names where every combination of
        election_ids × parties has votes > 0.
        """
        required = len(election_ids) * len(parties)
        valid = (
            totals[
                totals["election_id"].isin(election_ids)
                & totals["party"].isin(parties)
                & (totals["party_total"] > 0)
            ]
            .groupby("contest_name")
            .filter(lambda g: len(g) == required)["contest_name"]
            .unique()
        )
        return set(valid)

    # ------------------------------------------------------------------
    # Analysis: percent change by party
    # ------------------------------------------------------------------

    def pct_change_by_party(
        self,
        election_a: str | int | Election,
        election_b: str | int | Election,
        parties: tuple[str, ...] = ("DEM", "REP"),
        comparable_only: bool = True,
    ) -> pd.DataFrame:
        """
        For each contest, show vote totals for each party in both elections
        and the % change from election_a to election_b.

        Args:
            election_a:      The baseline election (name, id, or Election).
            election_b:      The comparison election (name, id, or Election).
            parties:         Parties to include. Default: DEM and REP.
            comparable_only: If True (default), include only contests where
                             both parties have votes in both elections.
                             If False, include all contests present in either
                             election, with NaN where data is missing.

        Returns:
            DataFrame with columns:
                contest,
                <party> <election_a.name>, <party> <election_b.name>,
                <party> % change,
                ... (repeated per party)
        """
        a, b = _resolve_elections(self._db, [election_a, election_b])
        totals = self._get_party_totals([a.id, b.id], parties)

        if comparable_only:
            contests = self._comparable_contests(totals, [a.id, b.id], parties)
        else:
            contests = set(totals["contest_name"].unique())

        if not contests:
            return pd.DataFrame(columns=["contest"])

        df = totals[totals["contest_name"].isin(contests)].copy()

        pivot = df.pivot_table(
            index="contest_name",
            columns=["party", "election_name"],
            values="party_total",
        )
        pivot.columns = [f"{party} {name}" for party, name in pivot.columns]
        pivot = pivot.reset_index()

        for party in parties:
            col_a = f"{party} {a.name}"
            col_b = f"{party} {b.name}"
            if col_a in pivot.columns and col_b in pivot.columns:
                pivot[f"{party} % change"] = (pivot[col_b] - pivot[col_a]) / pivot[
                    col_a
                ]

        # Order: contest, then per-party block of [a, b, % change]
        ordered = ["contest_name"]
        for party in parties:
            col_a = f"{party} {a.name}"
            col_b = f"{party} {b.name}"
            pct = f"{party} % change"
            for col in [col_a, col_b, pct]:
                if col in pivot.columns:
                    ordered.append(col)

        return pivot[ordered].rename(columns={"contest_name": "contest"})

    # ------------------------------------------------------------------
    # Analysis: party share of total votes
    # ------------------------------------------------------------------

    def party_share(
        self,
        *elections: str | int | Election,
        parties: tuple[str, ...] = ("DEM", "REP"),
        comparable_only: bool = True,
    ) -> pd.DataFrame:
        """
        For each contest, show each party's share of total votes cast in
        that contest per election.

        Accepts any number of elections (2+).

        Args:
            *elections:      Election names, ids, or Election objects.
            parties:         Parties to include. Default: DEM and REP.
            comparable_only: If True (default), include only contests where
                             both parties have votes in all elections.
                             If False, include all contests present in any
                             election, with NaN where data is missing.

        Returns:
            DataFrame with columns:
                contest,
                <party> share <election.name>,  (fraction, e.g. 0.52)
                ... (one column per election, per party)
                <party> pp change  (last minus first election, in percentage
                                    points as a fraction, e.g. 0.20 = +20 pp)
                ... (one pp change column per party)
        """
        if len(elections) < 2:
            raise ValueError("party_share requires at least 2 elections.")

        resolved = _resolve_elections(self._db, list(elections))
        election_ids = [e.id for e in resolved]

        totals = self._get_party_totals(election_ids, parties)

        if comparable_only:
            contests = self._comparable_contests(totals, election_ids, parties)
        else:
            contests = set(totals["contest_name"].unique())

        if not contests:
            return pd.DataFrame(columns=["contest"])

        # All-party totals per contest per election for denominator
        all_totals = self._db.query(
            f"""
            SELECT e.id AS election_id, e.name AS election_name,
                   co.contest_name,
                   SUM(ca.total_votes) AS contest_total
            FROM candidates ca
            JOIN contests  co ON ca.contest_id  = co.id
            JOIN elections e  ON ca.election_id = e.id
            WHERE e.id IN ({_placeholders(len(election_ids))})
              AND co.is_legislation = 0
            GROUP BY e.id, co.contest_name
            """,    # nosec B608 - placeholders only, values passed as parameters
            election_ids,
        )

        df = totals[totals["contest_name"].isin(contests)].copy()
        df = df.merge(all_totals, on=["election_id", "election_name", "contest_name"])
        df["vote_share"] = df["party_total"] / df["contest_total"]

        pivot = df.pivot_table(
            index="contest_name",
            columns=["party", "election_name"],
            values="vote_share",
        )
        pivot.columns = [f"{party} share {name}" for party, name in pivot.columns]
        pivot = pivot.reset_index()

        # Add a percentage-point change column per party (last minus first election)
        # Sort by date to find endpoints regardless of the order passed in
        by_date = sorted(resolved, key=lambda e: e.election_date or date(e.year, 1, 1))
        first, last = by_date[0], by_date[-1]
        for party in parties:
            col_first = f"{party} share {first.name}"
            col_last = f"{party} share {last.name}"
            if col_first in pivot.columns and col_last in pivot.columns:
                pivot[f"{party} pp change"] = pivot[col_last] - pivot[col_first]

        # Order: contest, then per-party block [each election share..., pp change]
        ordered = ["contest_name"]
        for party in parties:
            for e in resolved:
                col = f"{party} share {e.name}"
                if col in pivot.columns:
                    ordered.append(col)
            pp_col = f"{party} pp change"
            if pp_col in pivot.columns:
                ordered.append(pp_col)

        return pivot[ordered].rename(columns={"contest_name": "contest"})

    # ------------------------------------------------------------------
    # Analysis: turnout
    # ------------------------------------------------------------------

    def turnout(self, *elections: str | int | Election) -> pd.DataFrame:
        """
        Return registered voters, ballots cast, and turnout rate
        for the specified elections (or all elections if none given).

        Returns:
            DataFrame indexed by Metric with elections as columns.
        """
        if elections:
            resolved = _resolve_elections(self._db, list(elections))
        else:
            resolved = self._db.get_all_elections()

        rows = {
            "% Vote": {},
            "Registered": {},
            "Ballots Cast": {},
        }
        for e in resolved:
            rows["Registered"][e.name] = e.registered_voters
            rows["Ballots Cast"][e.name] = e.ballots_cast
            if e.registered_voters and e.ballots_cast:
                rows["% Vote"][e.name] = e.ballots_cast / e.registered_voters
            else:
                rows["% Vote"][e.name] = None

        result = pd.DataFrame(rows).T
        result.index.name = "Metric"
        return result

    # ------------------------------------------------------------------
    # Analysis: aggregated CSV
    # ------------------------------------------------------------------

    def aggregated_csv(self, *elections: str | int | Election) -> pd.DataFrame:
        """
        Return a flat table of every candidate row across the specified
        elections (or all elections if none given), combining the original
        source columns with election-level metadata.

        This is a raw data export — no filtering, pivoting, or comparable-
        contest logic is applied.

        Args:
            *elections: Election names, ids, or Election objects.
                        If omitted, all elections in the database are included.

        Returns:
            DataFrame with one row per candidate, columns:

            Original source columns (using original CSV header names):
                line number, contest name, choice name, party,
                total votes, percent of votes, registered voters, ballots cast,
                num precinct total, num precinct rptg, over votes, under votes

            Added columns:
                year, election name, category, contest name (normalized)
        """
        if elections:
            resolved = _resolve_elections(self._db, list(elections))
            election_ids = [e.id for e in resolved]
        else:
            election_ids = [e.id for e in self._db.get_all_elections()]

        if not election_ids:
            return pd.DataFrame()

        df = self._db.query(
            f"""
            SELECT
                ca.line_number          AS "line number",
                ca.contest_name_raw     AS "contest name",
                ca.choice_name          AS "choice name",
                ca.party                AS "party",
                ca.total_votes          AS "total votes",
                ca.percent_of_votes     AS "percent of votes",
                ca.registered_voters    AS "registered voters",
                ca.ballots_cast         AS "ballots cast",
                ca.num_precinct_total   AS "num precinct total",
                ca.num_precinct_rptg    AS "num precinct rptg",
                ca.over_votes           AS "over votes",
                ca.under_votes          AS "under votes",
                ca.year                 AS "year",
                e.category              AS "category",
                ca.contest_name         AS "contest name (normalized)",
                ca.election_name        AS "election name"
            FROM candidates ca
            JOIN elections e ON ca.election_id = e.id
            WHERE e.id IN ({_placeholders(len(election_ids))})
            ORDER BY ca.year, ca.contest_name, ca.party, ca.choice_name
            """,  # nosec B608 - placeholders only, values passed as parameters
            election_ids,
        )
        return df
