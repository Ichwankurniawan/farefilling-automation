"""
Covers categories/base.py's _copy_ai_fields() -- the mechanism that
makes per-cell (not per-row) AI highlighting possible. Formalizes the
four cases already verified by hand while building that fix.
"""
from categories.base import CategoryResolver


def make_resolver():
    return CategoryResolver()


def test_ai_fills_both_previously_empty_fields():
    entry = {"A": None, "B": None}
    ai_result = {"A": "foo", "B": "bar"}
    make_resolver()._copy_ai_fields(entry, ai_result, ["A", "B"])
    assert entry == {"A": "foo", "B": "bar", "ai_fields": {"A", "B"}}


def test_deterministic_value_wins_over_ai_and_is_not_marked():
    # The exact "regex already found A, AI only fills B" case CAT15's
    # real code relies on -- a pre-existing value must never be
    # overwritten by an AI guess, and must never be marked as if it had
    # been.
    entry = {"A": "regex-value", "B": None}
    ai_result = {"A": "ai-value-should-be-ignored", "B": "ai-value-used"}
    make_resolver()._copy_ai_fields(entry, ai_result, ["A", "B"])
    assert entry == {"A": "regex-value", "B": "ai-value-used", "ai_fields": {"B"}}


def test_ai_has_nothing_either_stays_none_not_marked():
    entry = {"A": None}
    ai_result = {"A": None}
    make_resolver()._copy_ai_fields(entry, ai_result, ["A"])
    assert entry == {"A": None, "ai_fields": set()}


def test_two_separate_ai_calls_union_not_overwrite():
    # CAT15 makes two independent AI calls that can both contribute to
    # the same entry -- the second call's _copy_ai_fields must not erase
    # what the first one already marked.
    entry = {"A": None, "B": None}
    resolver = make_resolver()
    resolver._copy_ai_fields(entry, {"A": "x"}, ["A"])
    resolver._copy_ai_fields(entry, {"B": "y"}, ["B"])
    assert entry == {"A": "x", "B": "y", "ai_fields": {"A", "B"}}
