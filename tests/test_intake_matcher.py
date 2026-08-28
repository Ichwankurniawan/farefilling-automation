"""
Covers intake_matcher.py's RULE detection and Rule & Tariff parsing --
including bug #28 (Excel error values getting treated as candidate RULE
codes) and the normalize_rule_and_tariffs() dedup that closed the
casing-drift bug between this module and run_new_filing.py's CLI path.
"""
import intake_matcher as im


class TestLooksLikeRuleCode:
    def test_real_rule_codes_accepted(self):
        assert im._looks_like_rule_code("CNF2") is True
        assert im._looks_like_rule_code("HKF1") is True
        assert im._looks_like_rule_code("3J8F") is True

    def test_excel_error_values_rejected(self):
        # bug #28: a broken cross-sheet formula's cached value ("#REF!")
        # used to pass this check and get treated as a second, genuinely
        # -disagreeing RULE, tripping the "never guess" safety check on
        # a false disagreement. Every standard Excel error string, not
        # just the one actually seen on a real file.
        for err in ("#REF!", "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#VALUE!", "#GETTING_DATA"):
            assert im._looks_like_rule_code(err) is False, err
        # Case-insensitivity -- Excel's own cached value is always this
        # exact casing, but the check itself shouldn't depend on it.
        assert im._looks_like_rule_code("#ref!") is False

    def test_none_and_label_fragments_rejected(self):
        assert im._looks_like_rule_code(None) is False
        assert im._looks_like_rule_code("Distribution :") is False  # has a space
        assert im._looks_like_rule_code("") is False


class TestNormalizeRuleAndTariffs:
    def test_uppercases_and_strips_both(self):
        rule, tariffs = im.normalize_rule_and_tariffs("hkf1", " fbra3p , fbrinpv ")
        assert rule == "HKF1"
        assert tariffs == ["FBRA3P", "FBRINPV"]

    def test_single_tariff(self):
        rule, tariffs = im.normalize_rule_and_tariffs("CNF2", "TEST1")
        assert (rule, tariffs) == ("CNF2", ["TEST1"])

    def test_empty_tariffs_list_on_blank_input(self):
        rule, tariffs = im.normalize_rule_and_tariffs("HKF1", "  ,  ,")
        assert rule == "HKF1"
        assert tariffs == []


class TestParseRuleTariffText:
    def test_multi_rule_multi_tariff(self):
        # The real field shape a user types: comma between groups
        # separates RULEs, comma inside a group separates TARIFFs for
        # the SAME rule -- must not be confused with each other.
        specs = im._parse_rule_tariff_text("HKF1 (FBRA23P), HKF2 (FBRA3P, FBRINPV)")
        assert specs == {"HKF1": ["FBRA23P"], "HKF2": ["FBRA3P", "FBRINPV"]}

    def test_lowercase_input_normalized(self):
        specs = im._parse_rule_tariff_text("hkf1(fbra3p)")
        assert specs == {"HKF1": ["FBRA3P"]}
