"""
Covers categories/base.py's generic _resolve_no_mapping() -- the shared
Type 1 fallback for every has_mapping=False category (CAT13, 18, 20-23,
26-29, 31, 33 -- confirmed via DataMapping that none of them has ANY
category-specific Excel column). Previously returned a blank entry
unconditionally, silently discarding whatever condition text existed.
Now captures real content into a JSON-only "Note" field (never written
to Excel -- there's nowhere to write it), gated the same way as every
other NONE-phrase check in this project so it's a zero-cost no-op
whenever the text is genuinely empty or the standard no-restriction
phrase.

Real-file verification (done separately, not here -- this suite makes
no real AI calls): CAT20 on real HKF1 data stayed free (0.00s, Note=null)
since its real text is the boilerplate phrase; CAT18/CAT23 (genuinely
rich real text) and CAT31/CAT33 (bare pointer-label text) all correctly
triggered AI and produced honest, non-hallucinated notes.
"""
import categories.base as base_module
from categories.cat13_accompanied_travel import Cat13Resolver
from categories.cat18_ticket_endorsement import Cat18Resolver


def _mock_extract_with_ai(condition_text, fare_context, spec_path, output_fields, field_labels=None):
    return {
        "Note": f"MOCKED SUMMARY OF: {condition_text[:20]}",
        "confidence": "LOW",
        "flag_reason": "MOCKED",
        "ai_used": True,
        "ai_fields": {"Note"},
    }


class _FakePricebookData:
    def __init__(self, condition_text):
        self._condition_text = condition_text

    def get_fare_rules_row(self, cat):
        return {"FARE RULE CONDITIONS": self._condition_text, "CAT": cat}


def test_empty_text_stays_free_no_ai_call():
    bundle = Cat13Resolver().resolve("TEST", _FakePricebookData(None), 1)
    entry = bundle["entries"][0]
    assert bundle["source_branch"] == "NO_CATEGORY_MAPPING"
    assert entry == {"Note": None, "confidence": "HIGH", "flag_reason": None}


def test_none_phrase_stays_free_no_ai_call():
    bundle = Cat13Resolver().resolve("TEST", _FakePricebookData("NONE UNLESS OTHERWISE SPECIFIED"), 1)
    assert bundle["source_branch"] == "NO_CATEGORY_MAPPING"
    assert bundle["entries"][0]["Note"] is None


def test_the_other_recognized_none_phrase_also_stays_free():
    bundle = Cat13Resolver().resolve("TEST", _FakePricebookData("UNLESS OTHERWISE SPECIFIED DOES NOT APPLY"), 1)
    assert bundle["source_branch"] == "NO_CATEGORY_MAPPING"


def test_real_content_reaches_ai_and_note_is_captured(monkeypatch):
    monkeypatch.setattr(base_module, "extract_with_ai", _mock_extract_with_ai)
    bundle = Cat18Resolver().resolve("TEST", _FakePricebookData("A REAL RULE APPLIES HERE."), 1)
    entry = bundle["entries"][0]
    assert bundle["source_branch"] == "AI_EXTRACTED_NOTE_ONLY"
    assert entry["Note"].startswith("MOCKED SUMMARY OF:")
    assert entry["confidence"] == "LOW"
    assert entry["ai_used"] is True


def test_no_get_fare_rules_row_method_is_treated_as_empty():
    # Defensive path -- mirrors common_fields.py's hasattr() guard.
    # sheet_type is only 1 here (Type 2/3 never reaches this method at
    # all, see resolve()'s branch order), so pricebook_data is always
    # PricebookData in practice, but the guard should still degrade
    # gracefully rather than crash if that ever isn't true.
    class _NoRowMethod:
        pass

    bundle = Cat13Resolver().resolve("TEST", _NoRowMethod(), 1)
    assert bundle["source_branch"] == "NO_CATEGORY_MAPPING"
    assert bundle["entries"][0]["Note"] is None
