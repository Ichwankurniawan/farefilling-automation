"""
Covers cat08_stopovers.py's NONE-phrase short-circuit. Confirmed by a real
live-AI test (not just reasoning about the code) that this category
previously had no such check at all, unlike CAT01/02/03/05/17 -- sending
"NONE UNLESS OTHERWISE SPECIFIED" straight to AI instead of returning a
free blank entry. Worse than just wasted cost (~38s, real tokens): the
real model misread the standalone word "NONE" in that boilerplate phrase
as answering MaxPermitted directly, returning MaxPermitted="NONE" -- a
genuinely misleading value (reads as "stopovers not permitted") for a
phrase that means nothing of the kind anywhere else in this project.
"""
from categories.cat08_stopovers import Cat08Resolver


class _FakePricebookData:
    """Minimal stand-in -- only get_fare_rules_row() is needed for CAT08."""

    def __init__(self, condition_text):
        self._condition_text = condition_text

    def get_fare_rules_row(self, cat):
        return {"FARE RULE CONDITIONS": self._condition_text, "CAT": cat}


def test_none_unless_specified_short_circuits_without_touching_ai():
    resolver = Cat08Resolver()
    bundle = resolver.resolve("TEST", _FakePricebookData("NONE UNLESS OTHERWISE SPECIFIED"), 1)
    entry = bundle["entries"][0]

    assert bundle["source_branch"] == "NONE_UNLESS_SPECIFIED"
    assert entry["confidence"] == "HIGH"
    assert entry["flag_reason"] is None
    # The real bug: MaxPermitted used to come back "NONE" (the AI
    # misreading the phrase) instead of null.
    assert entry["MaxPermitted"] is None
    assert entry["Charge1NoCharge"] is None
    assert entry["ChargesApplyFor"] is None
    # Never went through extract_with_ai() at all -- that's the whole
    # point of the short-circuit.
    assert "ai_used" not in entry


def test_the_other_recognized_none_phrase_also_short_circuits():
    # CAT17's phrasing ("...DOES NOT APPLY") -- confirmed equivalent to
    # "NONE UNLESS OTHERWISE SPECIFIED" via base.py's NONE_PHRASES set.
    # Using _is_none_condition() here (not a literal single-string ==)
    # is what makes this second phrasing recognized too.
    resolver = Cat08Resolver()
    bundle = resolver.resolve("TEST", _FakePricebookData("UNLESS OTHERWISE SPECIFIED DOES NOT APPLY"), 1)
    assert bundle["source_branch"] == "NONE_UNLESS_SPECIFIED"


def test_no_row_found_still_returns_flagged_unrecognized():
    # Unrelated to the fix, but a real branch worth locking in while
    # this file exists -- confirms the fix's placement (before Branch 1)
    # doesn't disturb the "row is None" guard that runs before it.
    class _EmptyPricebookData:
        def get_fare_rules_row(self, cat):
            return None

    resolver = Cat08Resolver()
    bundle = resolver.resolve("TEST", _EmptyPricebookData(), 1)
    assert bundle["source_branch"] == "UNRECOGNIZED"
