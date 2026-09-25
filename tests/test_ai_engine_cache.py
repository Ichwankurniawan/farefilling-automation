"""
ai_engine.py's extraction cache -- keyed on (spec_path, condition_text,
output_fields, field_labels), deliberately EXCLUDING fare_context/rule_id.

Real bug this fixes: two RULEs (HKF1/HKF2) sharing byte-identical
condition text got genuinely different AI answers across separate real
runs (confirmed live -- CAT15's "TICKETS MAY ONLY BE SOLD IN HONGKONG AND
MACAU." extracted Hong Kong/Macau for HKF1 in one run and for HKF2 in
another, with the other rule blank both times), since the self-hosted
model has neither `temperature` nor `seed` pinned. Caching the first
real call's result and reusing it for every later call with the same
(spec, text, schema) makes repeat resolutions consistent, and avoids a
wasted duplicate AI call.
"""
import os

import ai_engine
import run_logger

SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "fare_filling_poc", "ai_specs", "no_mapping_note_spec.yaml")


def _set_openai_compatible_env(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_BASE_URL", "http://fake-host:1234/v1")
    monkeypatch.setenv("AI_MODEL", "fake-model")


def _reset_cache():
    ai_engine._extraction_cache.clear()


def test_second_identical_call_reuses_first_and_skips_the_real_call(monkeypatch):
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    call_count = {"n": 0}

    def fake_call(prompt, base_url, model):
        call_count["n"] += 1
        return '{"Note": "Sold only in Hong Kong and Macau."}', \
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    text = 'REFER TO TAB "Filing Instructions"\nTICKETS MAY ONLY BE SOLD IN HONGKONG AND MACAU.'

    result_hkf1 = ai_engine.extract_with_ai(text, {"rule_id": "HKF1", "category": "CAT15"},
                                             SPEC_PATH, ["Note"])
    result_hkf2 = ai_engine.extract_with_ai(text, {"rule_id": "HKF2", "category": "CAT15"},
                                             SPEC_PATH, ["Note"])

    assert call_count["n"] == 1, "second call with identical (spec, text, fields) must not hit the model again"
    assert result_hkf1["Note"] == result_hkf2["Note"] == "Sold only in Hong Kong and Macau."
    # The cached copy must be independent -- mutating one must not affect the other.
    result_hkf1["Note"] = "mutated"
    assert result_hkf2["Note"] == "Sold only in Hong Kong and Macau."


def test_different_condition_text_is_not_cached_together(monkeypatch):
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    responses = iter([
        ('{"Note": "First answer."}', {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
        ('{"Note": "Second answer."}', {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ])
    call_count = {"n": 0}

    def fake_call(prompt, base_url, model):
        call_count["n"] += 1
        return next(responses)

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    r1 = ai_engine.extract_with_ai("Text A", {"rule_id": "HKF1", "category": "CAT18"}, SPEC_PATH, ["Note"])
    r2 = ai_engine.extract_with_ai("Text B", {"rule_id": "HKF2", "category": "CAT18"}, SPEC_PATH, ["Note"])

    assert call_count["n"] == 2, "different condition text must not share a cache entry"
    assert r1["Note"] == "First answer."
    assert r2["Note"] == "Second answer."


def test_cache_hit_is_logged_as_cached_status(monkeypatch):
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    def fake_call(prompt, base_url, model):
        return '{"Note": "Some note."}', {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    ai_engine.extract_with_ai("Same text", {"rule_id": "HKF1", "category": "CAT20"}, SPEC_PATH, ["Note"])
    ai_engine.extract_with_ai("Same text", {"rule_id": "HKF2", "category": "CAT20"}, SPEC_PATH, ["Note"])

    statuses = [c["status"] for c in run_logger._ai_calls]
    assert statuses == ["ok", "cached"]


def test_whitespace_only_differences_still_share_a_cache_entry(monkeypatch):
    # Mirrors the real HKF1/HKF2 CAT16 "Notes" text, which differs ONLY
    # by a stray line break/extra spaces in HKF1's cell -- same business
    # content, previously treated as two distinct cache entries.
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    call_count = {"n": 0}

    def fake_call(prompt, base_url, model):
        call_count["n"] += 1
        return '{"Note": "USD 50 service fee applies."}', \
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    text_hkf1 = "A SERVICE FEE APPLIES PER TICKET/   \nREFUND THROUGH SQ TICKET OFFICE."
    text_hkf2 = "A SERVICE FEE APPLIES PER TICKET/ REFUND THROUGH SQ TICKET OFFICE."

    r1 = ai_engine.extract_with_ai(text_hkf1, {"rule_id": "HKF1", "category": "CAT16"}, SPEC_PATH, ["Note"])
    r2 = ai_engine.extract_with_ai(text_hkf2, {"rule_id": "HKF2", "category": "CAT16"}, SPEC_PATH, ["Note"])

    assert call_count["n"] == 1, "whitespace-only differences must not force a second real call"
    assert r1["Note"] == r2["Note"] == "USD 50 service fee applies."


def test_normalization_collapses_whitespace_before_it_reaches_the_prompt(monkeypatch):
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    seen_prompts = []

    def fake_call(prompt, base_url, model):
        seen_prompts.append(prompt)
        return '{"Note": "ok"}', {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    ai_engine.extract_with_ai("Line one.\n\n   Line two   with   gaps.",
                               {"rule_id": "HKF1", "category": "CAT16"}, SPEC_PATH, ["Note"])

    assert "Line one. Line two with gaps." in seen_prompts[0]
    assert "\n\n" not in seen_prompts[0].split('"""')[1]


def test_parse_failures_are_never_cached(monkeypatch):
    _set_openai_compatible_env(monkeypatch)
    _reset_cache()
    run_logger.set_log_file(os.devnull)

    call_count = {"n": 0}

    def fake_call(prompt, base_url, model):
        call_count["n"] += 1
        return "not valid json at all", {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_call)

    text = "Some text that fails to parse"
    r1 = ai_engine.extract_with_ai(text, {"rule_id": "HKF1", "category": "CAT21"}, SPEC_PATH, ["Note"])
    r2 = ai_engine.extract_with_ai(text, {"rule_id": "HKF2", "category": "CAT21"}, SPEC_PATH, ["Note"])

    assert call_count["n"] == 2, "a parse failure must not poison the cache for the next identical call"
    assert "Response parsing failed" in r1["flag_reason"]
    assert "Response parsing failed" in r2["flag_reason"]
