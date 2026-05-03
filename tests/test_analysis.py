"""
Tests for election_analysis.analysis (ElectionAnalyzer)
"""


import pytest
import pandas as pd

from src.election_analysis_generator.analysis import ElectionAnalyzer
from tests.conftest import seed_election


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_two_elections(db):
    """
    Two comparable elections:
      - ATTORNEY GENERAL: DEM + REP in both
      - COUNTY CLERK: DEM only in 2026 (not comparable)
      - REFERENDUM: no party (legislation, excluded from analysis)
    """
    seed_election(
        db,
        "2022 General Primary",
        2022,
        [
            {
                "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                "party": "DEM",
                "total_votes": 68000,
                "registered_voters": 636000,
                "ballots_cast": 145000,
            },
            {
                "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                "party": "REP",
                "total_votes": 63000,
                "registered_voters": 636000,
                "ballots_cast": 145000,
            },
            {
                "contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",
                "party": "DEM",
                "total_votes": 65000,
                "registered_voters": 636000,
                "ballots_cast": 145000,
            },
            {
                "contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",
                "party": "REP",
                "total_votes": 59000,
                "registered_voters": 636000,
                "ballots_cast": 145000,
            },
            {
                "contest_name_raw": "Referendum Question 1 (Vote For 1)",
                "party": None,
                "total_votes": 80000,
                "registered_voters": 636000,
                "ballots_cast": 145000,
            },
        ],
    )
    seed_election(
        db,
        "2026 General Primary",
        2026,
        [
            {
                "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                "party": "DEM",
                "total_votes": 100000,
                "registered_voters": 636000,
                "ballots_cast": 161000,
            },
            {
                "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                "party": "REP",
                "total_votes": 43000,
                "registered_voters": 636000,
                "ballots_cast": 161000,
            },
            {
                "contest_name_raw": "FOR COUNTY CLERK (Vote For 1)",
                "party": "DEM",
                "total_votes": 95000,
                "registered_voters": 636000,
                "ballots_cast": 161000,
            },
            # REP missing for COUNTY CLERK in 2026 — not comparable
        ],
    )
    return db


@pytest.fixture
def db_with_four_elections(db):
    """Four elections for multi-election party_share tests."""
    for year, dem, rep in [
        (2014, 14000, 72000),
        (2018, 81000, 66000),
        (2022, 68000, 63000),
        (2026, 100000, 43000),
    ]:
        seed_election(
            db,
            f"{year} General Primary",
            year,
            [
                {
                    "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                    "party": "DEM",
                    "total_votes": dem,
                    "registered_voters": 636000,
                    "ballots_cast": 145000,
                },
                {
                    "contest_name_raw": "FOR ATTORNEY GENERAL (Vote For 1)",
                    "party": "REP",
                    "total_votes": rep,
                    "registered_voters": 636000,
                    "ballots_cast": 145000,
                },
            ],
        )
    return db


@pytest.fixture
def analyzer(db_with_two_elections):
    return ElectionAnalyzer(db_with_two_elections)


# ---------------------------------------------------------------------------
# list_elections
# ---------------------------------------------------------------------------


class TestListElections:
    def test_returns_dataframe(self, analyzer):
        result = analyzer.list_elections()
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self, analyzer):
        result = analyzer.list_elections()
        for col in ["id", "name", "year", "election_date"]:
            assert col in result.columns

    def test_returns_all_elections(self, analyzer):
        result = analyzer.list_elections()
        assert len(result) == 2

    def test_ordered_by_year(self, analyzer):
        result = analyzer.list_elections()
        assert result.iloc[0]["year"] <= result.iloc[1]["year"]


# ---------------------------------------------------------------------------
# _resolve_elections (via public methods)
# ---------------------------------------------------------------------------


class TestResolveElections:
    def test_resolves_by_name(self, analyzer, db_with_two_elections):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert isinstance(result, pd.DataFrame)

    def test_resolves_by_id(self, analyzer, db_with_two_elections):
        e1 = db_with_two_elections.get_election_by_name("2022 General Primary")
        e2 = db_with_two_elections.get_election_by_name("2026 General Primary")
        result = analyzer.pct_change_by_party(e1.id, e2.id)
        assert isinstance(result, pd.DataFrame)

    def test_resolves_by_election_object(self, analyzer, db_with_two_elections):
        e1 = db_with_two_elections.get_election_by_name("2022 General Primary")
        e2 = db_with_two_elections.get_election_by_name("2026 General Primary")
        result = analyzer.pct_change_by_party(e1, e2)
        assert isinstance(result, pd.DataFrame)

    def test_raises_for_unknown_name(self, analyzer):
        with pytest.raises(ValueError, match="Election not found"):
            analyzer.pct_change_by_party("Nonexistent", "2026 General Primary")

    def test_raises_for_unknown_id(self, analyzer):
        with pytest.raises(ValueError, match="Election not found"):
            analyzer.pct_change_by_party(9999, 9998)


# ---------------------------------------------------------------------------
# pct_change_by_party
# ---------------------------------------------------------------------------


class TestPctChangeByParty:
    def test_returns_dataframe(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert isinstance(result, pd.DataFrame)

    def test_has_contest_column(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert "contest" in result.columns

    def test_has_vote_total_columns(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert "DEM 2022 General Primary" in result.columns
        assert "DEM 2026 General Primary" in result.columns

    def test_has_pct_change_columns(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert "DEM % change" in result.columns
        assert "REP % change" in result.columns

    def test_pct_change_calculation(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        row = result[result["contest"] == "FOR ATTORNEY GENERAL"].iloc[0]
        expected = (100000 - 68000) / 68000
        assert abs(row["DEM % change"] - expected) < 1e-6

    def test_excludes_non_comparable_contests(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert "FOR COUNTY CLERK" not in result["contest"].values

    def test_excludes_legislation(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert "REFERENDUM QUESTION 1" not in result["contest"].values

    def test_returns_empty_df_when_no_comparable_contests(self, db):
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 5000,
                },
            ],
        )
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR GOVERNOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 6000,
                },
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        assert len(result) == 0

    def test_column_order_dem_before_rep(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        cols = list(result.columns)
        dem_idx = next(i for i, c in enumerate(cols) if c.startswith("DEM"))
        rep_idx = next(i for i, c in enumerate(cols) if c.startswith("REP"))
        assert dem_idx < rep_idx

    def test_comparable_only_false_includes_non_comparable(self, analyzer):
        # COUNTY CLERK has no REP in 2026 so it's excluded when comparable_only=True
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary", comparable_only=False
        )
        assert "FOR COUNTY CLERK" in result["contest"].values

    def test_comparable_only_true_excludes_non_comparable(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary", comparable_only=True
        )
        assert "FOR COUNTY CLERK" not in result["contest"].values

    def test_comparable_only_false_has_nan_for_missing_data(self, analyzer):
        result = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary", comparable_only=False
        )
        row = result[result["contest"] == "FOR COUNTY CLERK"].iloc[0]
        # REP has no 2026 data — that cell should be NaN
        assert pd.isna(row["REP 2026 General Primary"])

    def test_comparable_only_defaults_to_true(self, analyzer):
        result_default = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary"
        )
        result_explicit = analyzer.pct_change_by_party(
            "2022 General Primary", "2026 General Primary", comparable_only=True
        )
        assert list(result_default["contest"]) == list(result_explicit["contest"])


# ---------------------------------------------------------------------------
# party_share
# ---------------------------------------------------------------------------


class TestPartyShare:
    def test_returns_dataframe(self, analyzer):
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        assert isinstance(result, pd.DataFrame)

    def test_has_contest_column(self, analyzer):
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        assert "contest" in result.columns

    def test_has_share_columns(self, analyzer):
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        assert "DEM share 2022 General Primary" in result.columns
        assert "REP share 2026 General Primary" in result.columns

    def test_share_sums_to_one_for_two_party_contest(self, db):
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 6000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 4000,
                },
            ],
        )
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 7000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 3000,
                },
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        row = result[result["contest"] == "FOR SENATOR"].iloc[0]
        assert (
            abs(
                row["DEM share 2022 General Primary"]
                + row["REP share 2022 General Primary"]
                - 1.0
            )
            < 1e-6
        )

    def test_share_calculation(self, db):
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 6000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 4000,
                },
            ],
        )
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 7000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 3000,
                },
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        row = result[result["contest"] == "FOR SENATOR"].iloc[0]
        assert abs(row["DEM share 2022 General Primary"] - 0.6) < 1e-6
        assert abs(row["REP share 2022 General Primary"] - 0.4) < 1e-6

    def test_accepts_four_elections(self, db_with_four_elections):
        analyzer = ElectionAnalyzer(db_with_four_elections)
        result = analyzer.party_share(
            "2014 General Primary",
            "2018 General Primary",
            "2022 General Primary",
            "2026 General Primary",
        )
        assert "DEM share 2014 General Primary" in result.columns
        assert "DEM share 2026 General Primary" in result.columns

    def test_raises_with_fewer_than_two_elections(self, analyzer):
        with pytest.raises(ValueError, match="at least 2"):
            analyzer.party_share("2022 General Primary")

    def test_excludes_legislation(self, analyzer):
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        assert "REFERENDUM QUESTION 1" not in result["contest"].values

    def test_comparable_only_false_includes_non_comparable(self, analyzer):
        result = analyzer.party_share(
            "2022 General Primary", "2026 General Primary", comparable_only=False
        )
        assert "FOR COUNTY CLERK" in result["contest"].values

    def test_comparable_only_true_excludes_non_comparable(self, analyzer):
        result = analyzer.party_share(
            "2022 General Primary", "2026 General Primary", comparable_only=True
        )
        assert "FOR COUNTY CLERK" not in result["contest"].values

    def test_comparable_only_defaults_to_true(self, analyzer):
        result_default = analyzer.party_share(
            "2022 General Primary", "2026 General Primary"
        )
        result_explicit = analyzer.party_share(
            "2022 General Primary", "2026 General Primary", comparable_only=True
        )
        assert list(result_default["contest"]) == list(result_explicit["contest"])

    def test_has_pp_change_columns(self, analyzer):
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        assert "DEM pp change" in result.columns
        assert "REP pp change" in result.columns

    def test_pp_change_calculation(self, db):
        # DEM: 40% in 2022, 60% in 2026 → +0.20
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 4000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 6000,
                },
            ],
        )
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 6000,
                },
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "REP",
                    "total_votes": 4000,
                },
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        row = result[result["contest"] == "FOR SENATOR"].iloc[0]
        assert abs(row["DEM pp change"] - 0.20) < 1e-6
        assert abs(row["REP pp change"] - (-0.20)) < 1e-6

    def test_pp_change_is_last_minus_first(self, db):
        # pp change should be 2026 minus 2014 regardless of the order elections are passed in
        for year, dem, rep in [
            (2014, 3000, 7000),
            (2018, 4000, 6000),
            (2022, 5000, 5000),
            (2026, 6000, 4000),
        ]:
            seed_election(
                db,
                f"{year} General Primary",
                year,
                [
                    {
                        "contest_name_raw": "FOR SENATOR (Vote For 1)",
                        "party": "DEM",
                        "total_votes": dem,
                    },
                    {
                        "contest_name_raw": "FOR SENATOR (Vote For 1)",
                        "party": "REP",
                        "total_votes": rep,
                    },
                ],
            )
        analyzer = ElectionAnalyzer(db)
        # Pass elections in reverse chronological order to prove sorting works
        result = analyzer.party_share(
            "2026 General Primary",
            "2022 General Primary",
            "2018 General Primary",
            "2014 General Primary",
        )
        row = result[result["contest"] == "FOR SENATOR"].iloc[0]
        # DEM: 0.30 in 2014, 0.60 in 2026 → +0.30
        assert abs(row["DEM pp change"] - 0.30) < 1e-6

    def test_pp_change_column_order(self, analyzer):
        # pp change should appear after all share columns for that party,
        # before the next party's columns
        result = analyzer.party_share("2022 General Primary", "2026 General Primary")
        cols = list(result.columns)
        dem_share_last = max(i for i, c in enumerate(cols) if c.startswith("DEM share"))
        dem_pp = next(i for i, c in enumerate(cols) if c == "DEM pp change")
        rep_share_first = next(
            i for i, c in enumerate(cols) if c.startswith("REP share")
        )
        assert dem_share_last < dem_pp < rep_share_first

    def test_pp_change_with_nan_when_not_comparable(self, analyzer):
        # comparable_only=False: contests missing a party in one election
        # should have NaN pp change for that party
        result = analyzer.party_share(
            "2022 General Primary", "2026 General Primary", comparable_only=False
        )
        row = result[result["contest"] == "FOR COUNTY CLERK"].iloc[0]
        # REP missing in 2026 → pp change is NaN
        assert pd.isna(row["REP pp change"])


# ---------------------------------------------------------------------------
# turnout
# ---------------------------------------------------------------------------


class TestTurnout:
    def test_returns_dataframe(self, analyzer):
        result = analyzer.turnout()
        assert isinstance(result, pd.DataFrame)

    def test_index_labels(self, analyzer):
        result = analyzer.turnout()
        assert list(result.index) == ["% Vote", "Registered", "Ballots Cast"]

    def test_columns_are_election_names(self, analyzer):
        result = analyzer.turnout()
        assert "2022 General Primary" in result.columns
        assert "2026 General Primary" in result.columns

    def test_pct_vote_calculation(self, db):
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 5000,
                },
            ],
            ballots_cast=25000,
            registered_voters=100000,
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.turnout()
        assert abs(result.loc["% Vote", "2022 General Primary"] - 0.25) < 1e-6

    def test_filters_to_specified_elections(self, analyzer):
        result = analyzer.turnout("2022 General Primary")
        assert "2022 General Primary" in result.columns
        assert "2026 General Primary" not in result.columns

    def test_returns_all_elections_when_none_specified(self, analyzer):
        result = analyzer.turnout()
        assert len(result.columns) == 2

    def test_index_name_is_metric(self, analyzer):
        result = analyzer.turnout()
        assert result.index.name == "Metric"


# ---------------------------------------------------------------------------
# aggregated_csv
# ---------------------------------------------------------------------------


class TestAggregatedCsv:
    EXPECTED_COLUMNS = [
        "line number",
        "contest name",
        "choice name",
        "party",
        "total votes",
        "percent of votes",
        "registered voters",
        "ballots cast",
        "num precinct total",
        "num precinct rptg",
        "over votes",
        "under votes",
        "year",
        "category",
        "contest name (normalized)",
        "election name",
    ]

    def test_returns_dataframe(self, analyzer):
        result = analyzer.aggregated_csv()
        assert isinstance(result, pd.DataFrame)

    def test_has_all_expected_columns(self, analyzer):
        result = analyzer.aggregated_csv()
        for col in self.EXPECTED_COLUMNS:
            assert col in result.columns, f"Missing column: {col!r}"

    def test_column_order(self, analyzer):
        result = analyzer.aggregated_csv()
        assert list(result.columns) == self.EXPECTED_COLUMNS

    def test_one_row_per_candidate(self, analyzer):
        # db_with_two_elections fixture has 5 + 3 = 8 candidate rows
        result = analyzer.aggregated_csv()
        assert len(result) == 8

    def test_filters_to_specified_elections(self, analyzer):
        result = analyzer.aggregated_csv("2022 General Primary")
        assert set(result["year"].unique()) == {2022}

    def test_includes_all_elections_when_none_specified(self, analyzer):
        result = analyzer.aggregated_csv()
        assert set(result["year"].unique()) == {2022, 2026}

    def test_normalized_contest_name_differs_from_raw(self, db):
        # Raw has "(Vote For 1)" suffix; normalized strips it
        seed_election(
            db,
            "2022 General Primary",
            2022,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "total_votes": 5000,
                },
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.aggregated_csv()
        row = result.iloc[0]
        assert row["contest name"] == "FOR SENATOR (Vote For 1)"
        assert row["contest name (normalized)"] == "FOR SENATOR"

    def test_year_column_populated(self, analyzer):
        result = analyzer.aggregated_csv("2022 General Primary")
        assert (result["year"] == 2022).all()

    def test_category_column_populated(self, analyzer):
        result = analyzer.aggregated_csv("2022 General Primary")
        assert (result["category"] == "General Primary").all()

    def test_includes_legislation_contests(self, analyzer):
        # aggregated_csv is a raw export — legislation is not filtered out
        result = analyzer.aggregated_csv("2022 General Primary")
        assert "Referendum Question 1 (Vote For 1)" in result["contest name"].values

    def test_empty_dataframe_when_no_elections_in_db(self, db):
        analyzer = ElectionAnalyzer(db)
        result = analyzer.aggregated_csv()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_accepts_election_objects(self, db_with_two_elections):
        analyzer = ElectionAnalyzer(db_with_two_elections)
        election = db_with_two_elections.get_election_by_name("2022 General Primary")
        result = analyzer.aggregated_csv(election)
        assert set(result["year"].unique()) == {2022}


# ---------------------------------------------------------------------------
# precinct_turnout
# ---------------------------------------------------------------------------


def _seed_precinct_data(db, election_name, year, rows):
    """
    Helper: seed an election with summary candidates AND precinct results.
    rows is a list of dicts with keys:
        contest_name_raw, party, choice_name, summary_votes,
        precinct, registered_voters, early_votes, vote_by_mail,
        polling, provisional, total_votes
    """
    from tests.conftest import seed_election

    # Deduplicate summary rows (one per contest × party × candidate)
    seen = set()
    summary_rows = []
    for r in rows:
        key = (r["contest_name_raw"], r.get("party"), r.get("choice_name", "Jane Smith"))
        if key not in seen:
            seen.add(key)
            summary_rows.append(
                {
                    "contest_name_raw": r["contest_name_raw"],
                    "party": r.get("party", "DEM"),
                    "choice_name": r.get("choice_name", "Jane Smith"),
                    "total_votes": r.get("summary_votes", r.get("total_votes", 100)),
                }
            )

    election = seed_election(db, election_name, year, summary_rows)

    contest_id = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()[0]

    precinct_rows = []
    for r in rows:
        precinct_rows.append(
            {
                "election_id": election.id,
                "contest_id": contest_id,
                "contest_name_raw": r["contest_name_raw"],
                "choice_name": r.get("choice_name", "Jane Smith"),
                "precinct": r["precinct"],
                "registered_voters": r.get("registered_voters", 500),
                "early_votes": r.get("early_votes", 0),
                "vote_by_mail": r.get("vote_by_mail", 0),
                "polling": r.get("polling", r.get("total_votes", 50)),
                "provisional": r.get("provisional", 0),
                "total_votes": r.get("total_votes", 50),
            }
        )
    db.insert_precinct_results(precinct_rows)
    return election


class TestPrecinctTurnout:
    # ------------------------------------------------------------------ #
    # Basic shape / contract                                               #
    # ------------------------------------------------------------------ #

    def test_returns_dataframe(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 500,
                    "polling": 61,
                    "total_votes": 61,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 500,
                    "polling": 61,
                    "total_votes": 61,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        for col in [
            "election",
            "year",
            "contest",
            "party",
            "candidate",
            "precinct",
            "registered_voters",
            "early_votes",
            "vote_by_mail",
            "polling",
            "provisional",
            "total_votes",
            "turnout_rate",
        ]:
            assert col in result.columns, f"Missing column: {col!r}"

    def test_returns_empty_df_when_no_precinct_data(self, db):
        seed_election(
            db,
            "2026 General Primary",
            2026,
            [{"contest_name_raw": "FOR SENATOR (Vote For 1)", "party": "DEM"}],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_returns_empty_df_when_no_elections_in_db(self, db):
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    # ------------------------------------------------------------------ #
    # Filtering                                                            #
    # ------------------------------------------------------------------ #

    def test_filters_to_specified_election(self, db):
        for year, name in [(2022, "2022 General Primary"), (2026, "2026 General Primary")]:
            _seed_precinct_data(
                db,
                name,
                year,
                [
                    {
                        "contest_name_raw": "FOR SENATOR (Vote For 1)",
                        "party": "DEM",
                        "choice_name": "Jane Smith",
                        "precinct": "Addison 001",
                        "total_votes": 50,
                    }
                ],
            )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout("2026 General Primary")
        assert set(result["year"].unique()) == {2026}

    def test_returns_all_elections_when_none_specified(self, db):
        for year, name in [(2022, "2022 General Primary"), (2026, "2026 General Primary")]:
            _seed_precinct_data(
                db,
                name,
                year,
                [
                    {
                        "contest_name_raw": "FOR SENATOR (Vote For 1)",
                        "party": "DEM",
                        "choice_name": "Jane Smith",
                        "precinct": "Addison 001",
                        "total_votes": 50,
                    }
                ],
            )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert set(result["year"].unique()) == {2022, 2026}

    def test_excludes_legislation_contests(self, db):
        from tests.conftest import make_candidates_df
        from src.election_analysis_generator.models import Election

        election = Election(
            id=None,
            name="2026 General Primary",
            year=2026,
            election_date=None,
            results_last_updated=None,
            summary_file="2026-gp.csv",
        )
        df = make_candidates_df(
            [{"contest_name_raw": "Referendum Question 1 (Vote For 1)", "party": None}]
        )
        election, _ = db.insert_election(election, df)
        db.register_file(election.summary_file, election.id)

        contest_id = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()[0]
        db.insert_precinct_results(
            [
                {
                    "election_id": election.id,
                    "contest_id": contest_id,
                    "contest_name_raw": "Referendum Question 1 (Vote For 1)",
                    "choice_name": "Yes",
                    "precinct": "Addison 001",
                    "registered_voters": 500,
                    "early_votes": 0,
                    "vote_by_mail": 0,
                    "polling": 300,
                    "provisional": 0,
                    "total_votes": 300,
                }
            ]
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert "REFERENDUM QUESTION 1" not in result["contest"].values

    # ------------------------------------------------------------------ #
    # turnout_rate calculation                                             #
    # ------------------------------------------------------------------ #

    def test_turnout_rate_calculation(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 400,
                    "polling": 100,
                    "total_votes": 100,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        row = result.iloc[0]
        assert abs(row["turnout_rate"] - 0.25) < 1e-6

    def test_turnout_rate_is_nan_when_registered_voters_is_null(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": None,
                    "polling": 100,
                    "total_votes": 100,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert pd.isna(result.iloc[0]["turnout_rate"])

    def test_turnout_rate_is_nan_when_registered_voters_is_zero(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 0,
                    "polling": 100,
                    "total_votes": 100,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert pd.isna(result.iloc[0]["turnout_rate"])

    # ------------------------------------------------------------------ #
    # Resolve elections (names, ids, Election objects)                     #
    # ------------------------------------------------------------------ #

    def test_resolves_by_name(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "total_votes": 50,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout("2026 General Primary")
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_resolves_by_id(self, db):
        election = _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "total_votes": 50,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout(election.id)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_raises_for_unknown_election_name(self, db):
        analyzer = ElectionAnalyzer(db)
        with pytest.raises(ValueError, match="Election not found"):
            analyzer.precinct_turnout("Nonexistent Election")

    # ------------------------------------------------------------------ #
    # Vote component columns                                               #
    # ------------------------------------------------------------------ #

    def test_vote_components_stored_correctly(self, db):
        _seed_precinct_data(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 1000,
                    "early_votes": 10,
                    "vote_by_mail": 20,
                    "polling": 30,
                    "provisional": 1,
                    "total_votes": 61,
                }
            ],
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        row = result.iloc[0]
        assert row["early_votes"] == 10
        assert row["vote_by_mail"] == 20
        assert row["polling"] == 30
        assert row["provisional"] == 1
        assert row["total_votes"] == 61

    # ------------------------------------------------------------------ #
    # Multiple precincts / candidates                                      #
    # ------------------------------------------------------------------ #

    def test_multiple_precincts_returned(self, db):
        from tests.conftest import seed_election

        election = seed_election(
            db,
            "2026 General Primary",
            2026,
            [
                {
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "party": "DEM",
                    "choice_name": "Jane Smith",
                    "total_votes": 150,
                }
            ],
        )
        contest_id = db._conn.execute("SELECT id FROM contests LIMIT 1").fetchone()[0]
        db.insert_precinct_results(
            [
                {
                    "election_id": election.id,
                    "contest_id": contest_id,
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 001",
                    "registered_voters": 500,
                    "early_votes": 0,
                    "vote_by_mail": 0,
                    "polling": 61,
                    "provisional": 0,
                    "total_votes": 61,
                },
                {
                    "election_id": election.id,
                    "contest_id": contest_id,
                    "contest_name_raw": "FOR SENATOR (Vote For 1)",
                    "choice_name": "Jane Smith",
                    "precinct": "Addison 002",
                    "registered_voters": 400,
                    "early_votes": 0,
                    "vote_by_mail": 0,
                    "polling": 89,
                    "provisional": 0,
                    "total_votes": 89,
                },
            ]
        )
        analyzer = ElectionAnalyzer(db)
        result = analyzer.precinct_turnout()
        assert len(result) == 2
        assert set(result["precinct"].unique()) == {"Addison 001", "Addison 002"}
