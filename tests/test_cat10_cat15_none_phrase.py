"""
Covers cat10_combinations.py's Side Trips/Notes AI-fallback check and
cat15_sales_restrictions.py's Locations/Ticketing AI-fallback check --
found via a systematic sweep of every category with "NONE UNLESS
OTHERWISE SPECIFIED" as input, immediately after CAT08's own version of
this bug (bug #30) was fixed. Both had the same shape: a plain truthy
check ("if some_text:") with no exclusion for the recognized no-op
phrase, so a sub-row or condition text that was literally the standard
"no restriction" boilerplate still triggered a real AI call.
"""
import categories.cat10_combinations as cat10_module
import categories.cat15_sales_restrictions as cat15_module
from categories.cat10_combinations import Cat10Resolver
from categories.cat15_sales_restrictions import Cat15Resolver

NONE_TEXT = "NONE UNLESS OTHERWISE SPECIFIED"


def _mock_extract_with_ai(condition_text, fare_context, spec_path, output_fields, field_labels=None):
    """
    Stands in for the real extract_with_ai() -- this suite makes no real
    AI calls (see conftest.py / every other test file here), so the
    "still needs AI" tests below only need to confirm the call HAPPENS,
    not what a real model would say about the input.
    """
    entry = {f: None for f in output_fields}
    entry["confidence"] = "LOW"
    entry["flag_reason"] = "MOCKED"
    entry["ai_used"] = True
    entry["ai_fields"] = set()
    return entry


class _FakePricebookData:
    def __init__(self, condition_text=None, subrows=None):
        self._condition_text = condition_text
        self._subrows = subrows or {}

    def get_fare_rules_row(self, cat):
        return {"FARE RULE CONDITIONS": self._condition_text, "CAT": cat}

    def get_fare_rules_subrows(self, cat):
        return self._subrows

    def get_tab(self, name):
        return []

    def get_filing_instruction(self, key):
        return None


# ---- CAT10 ----

def test_cat10_none_phrase_subrows_short_circuit_without_ai():
    pb = _FakePricebookData(subrows={"Side Trips": NONE_TEXT, "Notes": NONE_TEXT})
    bundle = Cat10Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert entry["confidence"] == "HIGH"
    assert entry["flag_reason"] is None
    assert entry["SideTripsPermitted"] is None
    assert entry["Notes"] is None
    assert "ai_used" not in entry


def test_cat10_one_real_subrow_still_needs_ai(monkeypatch):
    # Only one of the two sub-rows is a real (non-None-phrase) value --
    # confirms the fix didn't over-correct into skipping AI whenever
    # EITHER field is the none-phrase, only when BOTH are.
    monkeypatch.setattr(cat10_module, "extract_with_ai", _mock_extract_with_ai)
    pb = _FakePricebookData(subrows={"Side Trips": "NOT PERMITTED", "Notes": NONE_TEXT})
    bundle = Cat10Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert entry["confidence"] == "LOW"
    assert entry["ai_used"] is True


def test_cat10_missing_subrows_key_still_returns_unrecognized():
    pb = _FakePricebookData(subrows={})
    bundle = Cat10Resolver().resolve("TEST", pb, 1)
    assert bundle["source_branch"] == "UNRECOGNIZED"


# ---- CAT15 ----

def test_cat15_none_phrase_main_condition_short_circuits_without_ai():
    pb = _FakePricebookData(condition_text=NONE_TEXT, subrows={})
    bundle = Cat15Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert entry["confidence"] == "HIGH"
    assert entry["flag_reason"] is None
    assert entry["Location1Value"] is None
    assert "ai_used" not in entry


def test_cat15_real_ticketing_mode_subrow_still_needs_ai_even_with_none_main_condition(monkeypatch):
    monkeypatch.setattr(cat15_module, "extract_with_ai", _mock_extract_with_ai)
    pb = _FakePricebookData(condition_text=NONE_TEXT, subrows={"Ticketing Mode": "ELECTRONIC TICKET ONLY"})
    bundle = Cat15Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert entry["confidence"] == "LOW"
    assert entry["ai_used"] is True
