"""
Covers cat16_penalties.py's Notes-sub-row AI extraction, added after the
NONE-phrase sweep found CAT16 had no AI call anywhere in its Type 1 path
at all (see bug #30 in CLAUDE.md). Confirmed against real HKF1/HKF2 files
(identical on both) that "Voluntary Change/Refund/No show" is always a
bare pointer to an unseen external document ("FARE FAMILY FEE CONDITIONS
- CAT16") -- never fed to AI -- while "Notes" has real, extractable
content (a flat per-ticket service fee description), which only grounds
7 of the real template's 34 category-specific columns.
"""
import categories.base as base_module
from categories.cat16_penalties import Cat16Resolver


def _mock_extract_with_ai(condition_text, fare_context, spec_path, output_fields, field_labels=None):
    entry = {f: None for f in output_fields}
    entry["confidence"] = "LOW"
    entry["flag_reason"] = "MOCKED"
    entry["ai_used"] = True
    entry["ai_fields"] = set(output_fields)
    return entry


class _FakePricebookData:
    def __init__(self, subrows):
        self._subrows = subrows

    def get_fare_rules_subrows(self, cat):
        return self._subrows


def test_no_subrows_at_all_returns_unrecognized():
    bundle = Cat16Resolver().resolve("TEST", _FakePricebookData({}), 1)
    assert bundle["source_branch"] == "UNRECOGNIZED"


def test_notes_none_phrase_short_circuits_without_ai():
    pb = _FakePricebookData({
        "Notes": "NONE UNLESS OTHERWISE SPECIFIED",
        "Voluntary Change/Refund/No show": "FARE FAMILY FEE CONDITIONS - CAT16",
    })
    bundle = Cat16Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert bundle["source_branch"] == "NO_EXTRACTABLE_CONTENT"
    assert entry["confidence"] == "HIGH"
    assert "ai_used" not in entry


def test_notes_missing_short_circuits_without_ai():
    # Only "Voluntary Change/Refund/No show" present, no "Notes" at all --
    # still nothing to extract (that sub-row is never read).
    pb = _FakePricebookData({"Voluntary Change/Refund/No show": "FARE FAMILY FEE CONDITIONS - CAT16"})
    bundle = Cat16Resolver().resolve("TEST", pb, 1)
    assert bundle["source_branch"] == "NO_EXTRACTABLE_CONTENT"


def test_real_notes_content_reaches_ai(monkeypatch):
    # CAT16 goes through the shared _ai_extract_entry() helper in
    # base.py (not a direct extract_with_ai import of its own), so the
    # patch target is base.py's bound name -- same as what actually gets
    # called.
    monkeypatch.setattr(base_module, "extract_with_ai", _mock_extract_with_ai)
    pb = _FakePricebookData({
        "Notes": "A SERVICE FEE OF <USD 50> APPLIES PER TICKET REQUIRING ISSUANCE/REISSUANCE/REVALIDATION/REFUND.",
        "Voluntary Change/Refund/No show": "FARE FAMILY FEE CONDITIONS - CAT16",
    })
    bundle = Cat16Resolver().resolve("TEST", pb, 1)
    entry = bundle["entries"][0]
    assert bundle["source_branch"] == "AI_EXTRACTED"
    assert entry["confidence"] == "LOW"
    assert entry["ai_used"] is True
