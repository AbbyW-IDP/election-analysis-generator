"""
Tests for election_analysis.normalize
"""

from src.election_analysis_generator.normalize import (
    normalize_contest_name,
    normalize_candidate_name,
    normalize_party,
)


class TestNormalizeContestName:
    def test_uppercase(self):
        assert normalize_contest_name("for attorney general") == "FOR ATTORNEY GENERAL"

    def test_strips_vote_for_parenthetical(self):
        assert (
            normalize_contest_name("FOR ATTORNEY GENERAL (Vote For 1)")
            == "FOR ATTORNEY GENERAL"
        )

    def test_strips_vacancy_parenthetical(self):
        result = normalize_contest_name(
            "FOR JUDGE OF THE CIRCUIT COURT (To fill the vacancy of the Honorable Jane Smith) (Vote For 1)"
        )
        assert result == "FOR JUDGE OF THE CIRCUIT COURT"

    def test_strips_party_suffix_d_star(self):
        assert (
            normalize_contest_name("United States Senator - D*")
            == "UNITED STATES SENATOR"
        )

    def test_strips_party_suffix_r_star(self):
        assert normalize_contest_name("FOR SENATOR - R*") == "FOR SENATOR"

    def test_strips_party_suffix_bare(self):
        assert normalize_contest_name("FOR SENATOR - R") == "FOR SENATOR"

    def test_strips_full_year_term(self):
        assert (
            normalize_contest_name(
                "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 FULL 4 YEAR TERM (Vote For 1)"
            )
            == "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1"
        )

    def test_strips_full_2_year_term(self):
        assert (
            normalize_contest_name(
                "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 FULL 2 YEAR TERM (Vote For 1)"
            )
            == "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1"
        )

    def test_strips_year_term_with_party_suffix(self):
        assert (
            normalize_contest_name(
                "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 4 Year Term - R"
            )
            == "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1"
        )

    def test_committeeman_to_committeeperson(self):
        assert (
            normalize_contest_name("FOR PRECINCT COMMITTEEMAN YORK 050 (Vote For 1)")
            == "FOR PRECINCT COMMITTEEPERSON YORK 050"
        )

    def test_committeewoman_to_committeeperson(self):
        assert (
            normalize_contest_name("FOR PRECINCT COMMITTEEWOMAN YORK 050 (Vote For 1)")
            == "FOR PRECINCT COMMITTEEPERSON YORK 050"
        )

    def test_congressman_to_congressperson(self):
        assert (
            normalize_contest_name("FOR CONGRESSMAN EIGHTH DISTRICT (Vote For 1)")
            == "FOR CONGRESSPERSON EIGHTH DISTRICT"
        )

    def test_chairman_to_chairperson(self):
        assert (
            normalize_contest_name("FOR CHAIRMAN OF THE COUNTY BOARD (Vote For 1)")
            == "FOR CHAIRPERSON OF THE COUNTY BOARD"
        )

    def test_ordinal_81st(self):
        assert (
            normalize_contest_name(
                "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 81ST REPRESENTATIVE DISTRICT (Vote For 1)"
            )
            == "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY EIGHTY-FIRST REPRESENTATIVE DISTRICT"
        )

    def test_ordinal_3rd(self):
        assert (
            normalize_contest_name(
                "FOR REPRESENTATIVE IN CONGRESS 3RD CONGRESSIONAL DISTRICT (Vote For 1)"
            )
            == "FOR REPRESENTATIVE IN CONGRESS THIRD CONGRESSIONAL DISTRICT"
        )

    def test_preserves_plain_integers(self):
        assert (
            normalize_contest_name(
                "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1 (Vote For 1)"
            )
            == "FOR MEMBER OF THE COUNTY BOARD DISTRICT 1"
        )

    def test_strips_all_transformations_combined(self):
        assert (
            normalize_contest_name("For Precinct Committeewoman York 050 (Vote For 1)")
            == "FOR PRECINCT COMMITTEEPERSON YORK 050"
        )

    def test_whitespace_trimmed(self):
        assert (
            normalize_contest_name("  FOR ATTORNEY GENERAL  ") == "FOR ATTORNEY GENERAL"
        )


class TestNormalizeParty:
    def test_d_to_dem(self):
        assert normalize_party("D") == "DEM"

    def test_r_to_rep(self):
        assert normalize_party("R") == "REP"

    def test_dem_passthrough(self):
        assert normalize_party("DEM") == "DEM"

    def test_rep_passthrough(self):
        assert normalize_party("REP") == "REP"

    def test_lowercase(self):
        assert normalize_party("d") == "DEM"

    def test_gp_passthrough(self):
        assert normalize_party("GP") == "GP"

    def test_wc_passthrough(self):
        assert normalize_party("WC") == "WC"

    def test_none_returns_none(self):
        assert normalize_party(None) is None

    def test_nan_returns_none(self):

        assert normalize_party(float("nan")) is None

    def test_unknown_party_returned_as_is(self):
        assert normalize_party("LIB") == "LIB"


class TestNormalizeCandidateName:
    # --- Pritzker correction (default corrections dict) ---

    def test_exact_match(self):
        assert normalize_candidate_name("JB PRITZER") == "JB PRITZKER"

    def test_case_insensitive(self):
        assert normalize_candidate_name("jb pritzer") == "JB PRITZKER"

    def test_mixed_case(self):
        assert normalize_candidate_name("JB Pritzer") == "JB PRITZKER"

    # --- Corrected value comes from the corrections dict exactly ---

    def test_corrected_value_is_from_corrections_dict(self):
        """The returned name is the dict value, not a transformation of the input."""
        assert normalize_candidate_name("jb pritzer") == "JB PRITZKER"

    # --- Non-matching cases — original value returned unchanged ---

    def test_different_name_unchanged(self):
        assert normalize_candidate_name("Janet PRITZER") == "Janet PRITZER"

    def test_correct_spelling_unchanged(self):
        assert normalize_candidate_name("JB PRITZKER") == "JB PRITZKER"

    def test_unrelated_candidate_unchanged(self):
        assert normalize_candidate_name("Jane Smith") == "Jane Smith"

    # --- Custom corrections dict ---

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
