"""
Formalizes the ad-hoc verification scripts written (and re-run by hand
each time) while building bug #25's fix -- date/case normalization at
template_writer.py's single write chokepoint. Every case here was
actually exercised against real files during that work; this just makes
sure a future change can't silently reintroduce it.
"""
import datetime

import template_writer as tw


class TestParseDateValue:
    def test_none_and_empty(self):
        assert tw._parse_date_value(None) is None
        assert tw._parse_date_value("") is None

    def test_real_datetime_and_date_passthrough(self):
        assert tw._parse_date_value(datetime.datetime(2026, 4, 1, 0, 0)) == datetime.date(2026, 4, 1)
        assert tw._parse_date_value(datetime.date(2026, 4, 1)) == datetime.date(2026, 4, 1)

    def test_ddmmmyy_text_variants(self):
        # All three separator/length shapes confirmed on real files.
        assert tw._parse_date_value("01APR26") == datetime.date(2026, 4, 1)
        assert tw._parse_date_value("1-Apr-2026") == datetime.date(2026, 4, 1)
        assert tw._parse_date_value("01 APR 2026") == datetime.date(2026, 4, 1)
        # Real value seen in a Type 3 sample.
        assert tw._parse_date_value("01-OCT-17") == datetime.date(2017, 10, 1)

    def test_iso_text(self):
        # Confirmed live during the fix: the same real pipeline run
        # produced both DD-MMM-YY and ISO from two different AI calls
        # on the same file -- both input shapes must parse.
        assert tw._parse_date_value("2017-10-01") == datetime.date(2017, 10, 1)
        assert tw._parse_date_value("2026-4-1") == datetime.date(2026, 4, 1)

    def test_unparseable_returns_none_not_a_guess(self):
        assert tw._parse_date_value("not a date") is None
        assert tw._parse_date_value("31FEB26") is None  # no such calendar date
        assert tw._parse_date_value("2026-13-40") is None  # no such month/day


class TestNormalizeOutputValue:
    def test_date_field_gets_normalized_and_formatted(self):
        value, number_format = tw._normalize_output_value("FirstDate", "01apr26")
        assert value == datetime.date(2026, 4, 1)
        assert number_format == "dd-mmm-yy"

    def test_string_fields_uppercase(self):
        value, number_format = tw._normalize_output_value("FareClassFamily", "kv6-")
        assert value == "KV6-"
        assert number_format is None

    def test_pricebook_name_exempt_from_uppercase(self):
        # Traceability identifier back to the real source file, not a
        # fare-filing code -- must survive exactly as typed.
        name = "v1-SAA+SQM(HKF1) Express Type 3 AFS Filing_Promotional fare"
        value, _fmt = tw._normalize_output_value("PRICEBOOK NAME", name)
        assert value == name

    def test_rule_field_uppercased(self):
        value, _fmt = tw._normalize_output_value("RULE", "hkf1")
        assert value == "HKF1"

    def test_none_passes_through(self):
        value, number_format = tw._normalize_output_value("OW/RT", None)
        assert value is None
        assert number_format is None

    def test_non_string_passes_through_unchanged(self):
        value, _fmt = tw._normalize_output_value("AltGenRule", 60)
        assert value == 60
