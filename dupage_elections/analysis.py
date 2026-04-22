"""
analysis.py
-----------
ElectionAnalyzer: a library of analyses that can be run against any
combination of elections in the database.

Analyses operate on election names or IDs and always return DataFrames.
Contests are matched across elections by normalized contest name.
"""

import pandas as pd

from dupage_elections.db import ElectionDatabase
from dupage_elections.models import Election


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
            raise TypeError(f"Expected election name, id, or Election object; got {type(e)}")
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
            SELECT id, name, year, election_date, results_last_updated,
                   ballots_cast, registered_voters, source_file
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
        id_placeholders = ",".join("?" * len(election_ids))
        party_placeholders = ",".join("?" * len(parties))

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
            WHERE e.id IN ({id_placeholders})
              AND ca.party IN ({party_placeholders})
              AND co.is_legislation = 0
            GROUP BY e.id, co.contest_name, ca.party
            """,
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
    ) -> pd.DataFrame:
        """
        For each comparable contest, show vote totals for each party in
        both elections and the % change from election_a to election_b.

        Args:
            election_a: The baseline election (name, id, or Election).
            election_b: The comparison election (name, id, or Election).
            parties:    Parties to include. Default: DEM and REP.

        Returns:
            DataFrame with columns:
                contest,
                <party> <election_a.name>, <party> <election_b.name>,
                <party> % change,
                ... (repeated per party)
        """
        a, b = _resolve_elections(self._db, [election_a, election_b])
        totals = self._get_party_totals([a.id, b.id], parties)
        comparable = self._comparable_contests(totals, [a.id, b.id], parties)

        if not comparable:
            return pd.DataFrame(columns=["contest"])

        df = totals[totals["contest_name"].isin(comparable)].copy()

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
                pivot[f"{party} % change"] = (pivot[col_b] - pivot[col_a]) / pivot[col_a]

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
    ) -> pd.DataFrame:
        """
        For each comparable contest, show each party's share of total votes
        cast in that contest per election.

        Accepts any number of elections (2+). Contests must have votes for
        all parties in all elections to be included.

        Args:
            *elections: Election names, ids, or Election objects.
            parties:    Parties to include. Default: DEM and REP.

        Returns:
            DataFrame with columns:
                contest,
                <party> share <election.name>,  (as a fraction, e.g. 0.52)
                ... (repeated per party per election)
        """
        if len(elections) < 2:
            raise ValueError("party_share requires at least 2 elections.")

        resolved = _resolve_elections(self._db, list(elections))
        election_ids = [e.id for e in resolved]

        totals = self._get_party_totals(election_ids, parties)
        comparable = self._comparable_contests(totals, election_ids, parties)

        if not comparable:
            return pd.DataFrame(columns=["contest"])

        # All-party totals per contest per election for denominator
        id_placeholders = ",".join("?" * len(election_ids))
        all_totals = self._db.query(
            f"""
            SELECT e.id AS election_id, e.name AS election_name,
                   co.contest_name,
                   SUM(ca.total_votes) AS contest_total
            FROM candidates ca
            JOIN contests  co ON ca.contest_id  = co.id
            JOIN elections e  ON ca.election_id = e.id
            WHERE e.id IN ({id_placeholders})
              AND co.is_legislation = 0
            GROUP BY e.id, co.contest_name
            """,
            election_ids,
        )

        df = totals[totals["contest_name"].isin(comparable)].copy()
        df = df.merge(all_totals, on=["election_id", "election_name", "contest_name"])
        df["vote_share"] = df["party_total"] / df["contest_total"]

        pivot = df.pivot_table(
            index="contest_name",
            columns=["party", "election_name"],
            values="vote_share",
        )
        pivot.columns = [f"{party} share {name}" for party, name in pivot.columns]
        pivot = pivot.reset_index()

        # Order: contest, then per-party block per election
        ordered = ["contest_name"]
        for party in parties:
            for e in resolved:
                col = f"{party} share {e.name}"
                if col in pivot.columns:
                    ordered.append(col)

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
