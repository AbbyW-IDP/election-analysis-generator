"""
Tests for election_analysis.normalize
"""

import pytest
from src.election_analysis_generator.normalize import (
    normalize_contest_name,
    normalize_candidate_name,
    normalize_party,
)


class TestNormalizeContestName:
    @pytest.mark.parametrize("raw, expected", [
        pytest.param("United States Senator - D*", "UNITED STATES SENATOR", id="d_star"),
        pytest.param("FOR SENATOR - R*",           "FOR SENATOR",           id="r_star"),
        pytest.param("FOR SENATOR - R",            "FOR SENATOR",           id="bare_r"),
    ])
    def test_strips_party_suffix(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "FOR ATTORNEY GENERAL (Vote For 1)",
            "FOR ATTORNEY GENERAL",
            id="vote_for",
        ),
        pytest.param(
            "FOR JUDGE OF THE CIRCUIT COURT (To fill the vacancy of the Honorable Jane Smith) (Vote For 1)",
            "FOR JUDGE OF THE CIRCUIT COURT",
            id="vacancy",
        ),
    ])
    def test_strips_parentheticals(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 FULL 4 YEAR TERM (Vote For 1)",
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1",
            id="full_4_year",
        ),
        pytest.param(
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 FULL 2 YEAR TERM (Vote For 1)",
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1",
            id="full_2_year",
        ),
        pytest.param(
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 4 Year Term - R",
            "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1",
            id="bare_year_term_with_party",
        ),
    ])
    def test_strips_year_term_suffix(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "FOR PRECINCT COMMITTEEMAN YORK 050 (Vote For 1)",
            "FOR PRECINCT COMMITTEEPERSON YORK 050",
            id="committeeman",
        ),
        pytest.param(
            "FOR PRECINCT COMMITTEEWOMAN YORK 050 (Vote For 1)",
            "FOR PRECINCT COMMITTEEPERSON YORK 050",
            id="committeewoman",
        ),
        pytest.param(
            "FOR CONGRESSMAN EIGHTH DISTRICT (Vote For 1)",
            "FOR CONGRESSPERSON EIGHTH DISTRICT",
            id="congressman",
        ),
        pytest.param(
            "FOR CHAIRMAN OF THE COUNTY BOARD (Vote For 1)",
            "FOR CHAIRPERSON OF THE COUNTY BOARD",
            id="chairman",
        ),
    ])
    def test_gender_neutral_titles(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 81ST REPRESENTATIVE DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY EIGHTY-FIRST REPRESENTATIVE DISTRICT",
            id="81st",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN CONGRESS 3RD CONGRESSIONAL DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN CONGRESS THIRD CONGRESSIONAL DISTRICT",
            id="3rd",
        ),
    ])
    def test_spells_out_ordinals(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    def test_uppercase(self):
        assert normalize_contest_name("for attorney general") == "FOR ATTORNEY GENERAL"

    def test_preserves_plain_integers(self):
        assert (
            normalize_contest_name("FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 (Vote For 1)")
            == "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1"
        )

    def test_whitespace_trimmed(self):
        assert normalize_contest_name("  FOR ATTORNEY GENERAL  ") == "FOR ATTORNEY GENERAL"

    def test_strips_all_transformations_combined(self):
        assert (
            normalize_contest_name("For Precinct Committeewoman York 050 (Vote For 1)")
            == "FOR PRECINCT COMMITTEEPERSON YORK 050"
        )


class TestNormalizeParty:
    @pytest.mark.parametrize("raw, expected", [
        pytest.param("D",   "DEM", id="d_to_dem"),
        pytest.param("d",   "DEM", id="lowercase_d"),
        pytest.param("DEM", "DEM", id="dem_passthrough"),
        pytest.param("R",   "REP", id="r_to_rep"),
        pytest.param("REP", "REP", id="rep_passthrough"),
        pytest.param("GP",  "GP",  id="gp_passthrough"),
        pytest.param("WC",  "WC",  id="wc_passthrough"),
        pytest.param("LIB", "LIB", id="unknown_passthrough"),
    ])
    def test_party_mapping(self, raw, expected):
        assert normalize_party(raw) == expected

    def test_none_returns_none(self):
        assert normalize_party(None) is None

    def test_nan_returns_none(self):
        assert normalize_party(float("nan")) is None


class TestNormalizeCandidateName:
    @pytest.mark.parametrize("name", [
        pytest.param("JB PRITZER",  id="uppercase"),
        pytest.param("jb pritzer",  id="lowercase"),
        pytest.param("JB Pritzer",  id="mixed_case"),
    ])
    def test_pritzker_correction(self, name):
        assert normalize_candidate_name(name) == "JB PRITZKER"

    @pytest.mark.parametrize("name", [
        pytest.param("Janet PRITZER", id="different_first_name"),
        pytest.param("JB PRITZKER",   id="already_correct"),
        pytest.param("Jane Smith",    id="unrelated"),
    ])
    def test_no_match_returns_original(self, name):
        assert normalize_candidate_name(name) == name

    def test_corrected_value_is_from_corrections_dict(self):
        """The returned name is the dict value, not a transformation of the input."""
        assert normalize_candidate_name("jb pritzer") == "JB PRITZKER"

    def test_custom_corrections_applied(self):
        custom = {"rob blagojevich": "ROD BLAGOJEVICH"}
        assert normalize_candidate_name("ROB BLAGOJEVICH", custom) == "ROD BLAGOJEVICH"

    def test_custom_corrections_replace_default(self):
        """Passing a custom dict does not also apply the default corrections."""
        custom = {"rob blagojevich": "ROD BLAGOJEVICH"}
        assert normalize_candidate_name("JB PRITZER", custom) == "JB PRITZER"

    def test_empty_corrections_dict_returns_original(self):
        assert normalize_candidate_name("JB PRITZER", {}) == "JB PRITZER"

    def test_multiple_corrections_all_applied(self):
        custom = {
            "jb pritzer": "JB PRITZKER",
            "rob blagojevich": "ROD BLAGOJEVICH",
        }
        assert normalize_candidate_name("ROB BLAGOJEVICH", custom) == "ROD BLAGOJEVICH"
        assert normalize_candidate_name("JB PRITZER", custom) == "JB PRITZKER"
