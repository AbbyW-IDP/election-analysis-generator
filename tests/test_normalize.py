"""
Tests for election_analysis.normalize
"""

import pytest
from src.election_analysis_generator.normalize import (
    ORDINAL_MAP,
    _ordinal_suffix,
    _ordinal_word,
    normalize_contest_name,
    normalize_candidate_name,
    normalize_party,
)


class TestNormalizeContestName:
    @pytest.mark.parametrize("raw, expected", [
        pytest.param("United States Senator - D*", "UNITED STATES SENATOR", id="d_star"),
        pytest.param("FOR SENATOR - R*",           "FOR SENATOR",           id="r_star"),
        pytest.param("FOR SENATOR - R",            "FOR SENATOR",           id="bare_r"),
        pytest.param("FOR STATE TREASURER - G",    "FOR STATE TREASURER",   id="bare_g"),
        pytest.param("FOR STATE TREASURER - G*",   "FOR STATE TREASURER",   id="g_star"),
        pytest.param("FOR STATE TREASURER - GP",   "FOR STATE TREASURER",   id="gp"),
    ])
    def test_strips_party_suffix(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    def test_strips_trailing_asterisk(self):
        assert normalize_contest_name("FOR GOVERNOR *") == "FOR GOVERNOR"

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
        pytest.param(
            "Judge of the Circuit Court, 18th Judicial Circuit - D (Fawell)",
            "JUDGE OF THE CIRCUIT COURT, EIGHTEENTH JUDICIAL CIRCUIT",
            id="trailing_paren_hides_party_suffix",
        ),
    ])
    def test_strips_parentheticals(self, raw, expected):
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "53 Trails Estates Unexpired 2 Year Park Commissioner (Vote For 0)",
            "53 TRAILS ESTATES PARK COMMISSIONER",
            id="mid_name_with_parenthetical",
        ),
        pytest.param(
            "Fox River Grove Unexpired 2 Year Village Trustee (Vote For 1)",
            "FOX RIVER GROVE VILLAGE TRUSTEE",
            id="mid_name_fox_river",
        ),
        pytest.param(
            "FOR JUDGE unexpired 6 year - D",
            "FOR JUDGE",
            id="trailing_with_party",
        ),
        pytest.param(
            "Addison Fire Protection Unexpired 4 Year Trustee",
            "ADDISON FIRE PROTECTION TRUSTEE",
            id="no_parenthetical",
        ),
    ])
    def test_strips_unexpired_year(self, raw, expected):
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
            id="81st_upper",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 81st REPRESENTATIVE DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY EIGHTY-FIRST REPRESENTATIVE DISTRICT",
            id="81st_lower",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN CONGRESS 3RD CONGRESSIONAL DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN CONGRESS THIRD CONGRESSIONAL DISTRICT",
            id="3rd_upper",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN CONGRESS 3rd CONGRESSIONAL DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN CONGRESS THIRD CONGRESSIONAL DISTRICT",
            id="3rd_lower",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 13TH REPRESENTATIVE DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY THIRTEENTH REPRESENTATIVE DISTRICT",
            id="13th_previously_missing",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 20TH REPRESENTATIVE DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY TWENTIETH REPRESENTATIVE DISTRICT",
            id="20th_decade",
        ),
        pytest.param(
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY 99TH REPRESENTATIVE DISTRICT (Vote For 1)",
            "FOR REPRESENTATIVE IN THE GENERAL ASSEMBLY NINETY-NINTH REPRESENTATIVE DISTRICT",
            id="99th_ceiling",
        ),
    ])
    def test_spells_out_ordinals(self, raw, expected):
        assert normalize_contest_name(raw) == expected


    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "Attorney General, State of Illinois - D*",
            "ATTORNEY GENERAL",
            id="attorney_general_state_of_illinois",
        ),
        pytest.param(
            "Governor and Lt Governor, State of Illinois - D*",
            "GOVERNOR AND LT GOVERNOR",
            id="governor_state_of_illinois",
        ),
        pytest.param(
            "Comptroller, State of Illinois - R",
            "COMPTROLLER",
            id="comptroller_state_of_illinois",
        ),
        pytest.param(
            "State Treasurer, State of Illinois - D",
            "STATE TREASURER",
            id="treasurer_state_of_illinois",
        ),
        pytest.param(
            "FOR ATTORNEY GENERAL (Vote For 1)",
            "FOR ATTORNEY GENERAL",
            id="unaffected_name_without_state_of_illinois",
        ),
    ])
    def test_strips_state_of_illinois_suffix(self, raw, expected):
        """', State of Illinois' is stripped before party suffix and uppercasing
        so that 2014/2018 names match the canonical 2022/2026 forms."""
        assert normalize_contest_name(raw) == expected


    @pytest.mark.parametrize("raw, expected", [
        pytest.param(
            "Tri-State Fire Protection - General Obligation Bonds (Vote For 1)",
            "TRI-STATE FIRE PROTECTION - GENERAL OBLIGATION BONDS",
            id="general_obligation_bonds_not_stripped_as_party_g",
        ),
        pytest.param(
            "Fox River Water Reclamation - General Operations (Vote For 1)",
            "FOX RIVER WATER RECLAMATION - GENERAL OPERATIONS",
            id="general_operations_not_stripped_as_party_g",
        ),
        pytest.param(
            "Downers Grove Sanitary District - General Obligation Bonds",
            "DOWNERS GROVE SANITARY DISTRICT - GENERAL OBLIGATION BONDS",
            id="general_obligation_no_parenthetical",
        ),
    ])
    def test_general_word_not_stripped_as_party_suffix(self, raw, expected):
        """'- G' in '- General ...' must not be treated as a Green Party suffix.
        The party suffix regex must only match when G is the final token, not
        when 'General' or other G-words follow the dash."""
        assert normalize_contest_name(raw) == expected


    @pytest.mark.parametrize("abbrev,township,precinct", [
        pytest.param("ADD", "ADDISON",      "004", id="ADD_addison"),
        pytest.param("BLM", "BLOOMINGDALE", "007", id="BLM_bloomingdale"),
        pytest.param("LSL", "LISLE",        "012", id="LSL_lisle"),
        pytest.param("MLT", "MILTON",       "045", id="MLT_milton"),
        pytest.param("NAP", "NAPERVILLE",   "003", id="NAP_naperville"),
        pytest.param("WYN", "WAYNE",        "002", id="WYN_wayne"),
        pytest.param("WNF", "WINFIELD",     "012", id="WNF_winfield"),
        pytest.param("YRK", "YORK",         "050", id="YRK_york"),
    ])
    def test_expands_township_abbreviations_in_committeeperson_names(
        self, abbrev, township, precinct
    ):
        """Abbreviated township names in precinct committeeperson contests are
        expanded to their full spellings so 2014/2018 names match 2022/2026."""
        raw = f"Precinct Committeeman {abbrev} {precinct} - D"
        expected = f"PRECINCT COMMITTEEPERSON {township} {precinct}"
        assert normalize_contest_name(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        pytest.param(
            "Precinct Committeeman D G 004 - D",
            "PRECINCT COMMITTEEPERSON DOWNERS GROVE 004",
            id="D_G_with_space",
        ),
        pytest.param(
            "Precinct Committeeman DG 025 - R",
            "PRECINCT COMMITTEEPERSON DOWNERS GROVE 025",
            id="DG_no_space",
        ),
    ])
    def test_expands_downers_grove_abbreviation_variants(self, raw, expected):
        """Both 'D G' and 'DG' are expanded to 'DOWNERS GROVE'."""
        assert normalize_contest_name(raw) == expected

    def test_township_abbreviations_not_expanded_outside_committeeperson(self):
        """Abbreviations like ADD, YRK are only expanded inside committeeperson names."""
        assert normalize_contest_name("ADDISON TOWNSHIP ASSESSOR") == "ADDISON TOWNSHIP ASSESSOR"
        assert normalize_contest_name("FOR COUNTY CLERK") == "FOR COUNTY CLERK"

    def test_full_township_spellings_unchanged(self):
        """Names already using full township spellings are not double-expanded."""
        assert normalize_contest_name(
            "FOR PRECINCT COMMITTEEMAN YORK 050 (Vote For 1)"
        ) == "FOR PRECINCT COMMITTEEPERSON YORK 050"
        assert normalize_contest_name(
            "FOR PRECINCT COMMITTEEMAN ADDISON 004 (Vote For 1)"
        ) == "FOR PRECINCT COMMITTEEPERSON ADDISON 004"


class TestOrdinalMap:
    """Tests for the generated ORDINAL_MAP and its helper functions."""

    def test_covers_1_to_99(self):
        for n in range(1, 100):
            suffix = _ordinal_suffix(n)
            assert suffix in ORDINAL_MAP, f"{suffix!r} missing from ORDINAL_MAP"

    def test_does_not_cover_0_or_100(self):
        assert _ordinal_suffix(0) not in ORDINAL_MAP
        assert _ordinal_suffix(100) not in ORDINAL_MAP

    @pytest.mark.parametrize("n, expected_suffix", [
        (1,  "1st"),
        (2,  "2nd"),
        (3,  "3rd"),
        (4,  "4th"),
        (11, "11th"),  # not 11st
        (12, "12th"),  # not 12nd
        (13, "13th"),  # not 13rd
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (99, "99th"),
    ])
    def test_ordinal_suffix(self, n, expected_suffix):
        assert _ordinal_suffix(n) == expected_suffix

    @pytest.mark.parametrize("n, expected_word", [
        (1,  "first"),
        (2,  "second"),
        (3,  "third"),
        (11, "eleventh"),
        (12, "twelfth"),
        (13, "thirteenth"),
        (20, "twentieth"),
        (21, "twenty-first"),
        (30, "thirtieth"),
        (50, "fiftieth"),
        (81, "eighty-first"),
        (99, "ninety-ninth"),
    ])
    def test_ordinal_word(self, n, expected_word):
        assert _ordinal_word(n) == expected_word

    def test_all_values_are_nonempty_strings(self):
        for suffix, word in ORDINAL_MAP.items():
            assert isinstance(word, str) and word, f"{suffix!r} maps to empty/non-string"

    def test_keys_are_lowercase(self):
        for key in ORDINAL_MAP:
            assert key == key.lower(), f"Key {key!r} is not lowercase"

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


class TestNormalizeIdempotency:
    @pytest.mark.parametrize("raw", [
        pytest.param("FOR ATTORNEY GENERAL (Vote For 1)",                    id="vote_for"),
        pytest.param("Judge of the Circuit Court, 18th Judicial Circuit - D", id="ordinal_party"),
        pytest.param("FOR STATE SENATOR - R*",                                id="party_star"),
        pytest.param("FOR REPRESENTATIVE IN CONGRESS 7TH CONGRESSIONAL DISTRICT", id="abbreviated_ordinal"),
        pytest.param("FOR JUDGE OF THE CIRCUIT COURT (To fill the vacancy of the Honorable Jane Smith) (Vote For 1)", id="vacancy"),
    ])
    def test_idempotent(self, raw):
        once = normalize_contest_name(raw)
        twice = normalize_contest_name(once)
        assert once == twice
