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
    # --- Pritzker correction (default corrections list) ---

    def test_exact_match(self):
        assert normalize_candidate_name("JB", "PRITZER") == ("JB", "PRITZKER")

    def test_case_insensitive_first_name(self):
        assert normalize_candidate_name("jb", "PRITZER") == ("JB", "PRITZKER")

    def test_case_insensitive_last_name(self):
        assert normalize_candidate_name("JB", "Pritzer") == ("JB", "PRITZKER")

    def test_case_insensitive_both(self):
        assert normalize_candidate_name("jb", "pritzer") == ("JB", "PRITZKER")

    # --- Corrected values come from the corrections list exactly ---

    def test_corrected_values_are_from_corrections_list(self):
        """The returned names are the correct_first/correct_last from the tuple,
        not a transformation of the input."""
        first, last = normalize_candidate_name("jb", "pritzer")
        assert first == "JB"
        assert last == "PRITZKER"

    # --- Punctuation is not stripped — must match exactly ---

    def test_dots_in_first_name_do_not_match(self):
        assert normalize_candidate_name("J.B.", "PRITZER") == ("J.B.", "PRITZER")

    def test_spaces_between_initials_do_not_match(self):
        assert normalize_candidate_name("J. B.", "PRITZER") == ("J. B.", "PRITZER")

    # --- Non-matching cases — original values returned unchanged ---

    def test_different_first_name_unchanged(self):
        assert normalize_candidate_name("Janet", "PRITZER") == ("Janet", "PRITZER")

    def test_correct_spelling_unchanged(self):
        assert normalize_candidate_name("JB", "PRITZKER") == ("JB", "PRITZKER")

    def test_unrelated_candidate_unchanged(self):
        assert normalize_candidate_name("Jane", "Smith") == ("Jane", "Smith")

    # --- Custom corrections iterable ---

    def test_custom_corrections_applied(self):
        custom = [("ROB", "BLAGOJEVICH", "ROD", "BLAGOJEVICH")]
        assert normalize_candidate_name("ROB", "BLAGOJEVICH", custom) == (
            "ROD",
            "BLAGOJEVICH",
        )

    def test_custom_corrections_replace_default(self):
        """Passing a custom list does not also apply the default corrections."""
        custom = [("ROB", "BLAGOJEVICH", "ROD", "BLAGOJEVICH")]
        assert normalize_candidate_name("JB", "PRITZER", custom) == ("JB", "PRITZER")

    def test_empty_corrections_list_returns_original(self):
        assert normalize_candidate_name("JB", "PRITZER", []) == ("JB", "PRITZER")

    def test_multiple_corrections_all_applied(self):
        custom = [
            ("JB", "PRITZER", "JB", "PRITZKER"),
            ("ROB", "BLAGOJEVICH", "ROD", "BLAGOJEVICH"),
        ]
        assert normalize_candidate_name("ROB", "BLAGOJEVICH", custom) == (
            "ROD",
            "BLAGOJEVICH",
        )
        assert normalize_candidate_name("JB", "PRITZER", custom) == ("JB", "PRITZKER")
