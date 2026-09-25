"""
Generic AI-extraction engine, shared by every category resolver.

Design (per the architecture decided earlier in the project): ONE engine
here builds the prompt, calls the LLM, and validates/parses the JSON
response against the category's output fields. Each category's specific
knowledge (which fields to fill, how to interpret its condition text)
lives in a small ai_specs/catXX_spec.yaml file, NOT in Python code here.

Every result from this engine is tagged confidence="LOW" and gets a
flag_reason -- per the project's standing rule that AI-derived fields
always get flagged for human review, never treated as HIGH confidence.

BACKEND SELECTION -- controlled by env vars (or ai_config.env next to this
file, loaded automatically -- see that file's comments), no code change
needed to switch:
  AI_PROVIDER=anthropic (default)
    Requires ANTHROPIC_API_KEY. Model set by AI_MODEL (default
    "claude-sonnet-4-5").
  AI_PROVIDER=openai_compatible
    For any self-hosted OpenAI-compatible server (Ollama, vLLM,
    text-generation-webui, LM Studio, etc. -- e.g. a Qwen model served
    locally). Requires AI_BASE_URL (e.g. "http://localhost:11434/v1" for
    Ollama, or "http://your-server:8000/v1" for vLLM) and AI_MODEL (the
    model name as your server expects it, e.g. "qwen2.5:32b"). AI_API_KEY
    is optional -- most self-hosted servers accept any non-empty string
    (the openai SDK requires *something* to be set even if the server
    doesn't check it), so this defaults to "not-needed" if unset.

If neither is configured (no key for the selected provider), falls back
to a clearly-labeled mock so the rest of the pipeline can still be
exercised end-to-end -- the mock is NOT a substitute for a real model
call and must never be mistaken for one downstream.
"""
import json
import os
import time
import yaml

import run_logger

def _load_ai_config():
    """
    Loads ai_config.env (KEY=VALUE per line, next to this file) into
    os.environ via setdefault -- so a real env var set outside this
    process always wins, and editing the file needs no shell/session
    setup (export / $env: differ across Windows PowerShell vs Linux bash,
    which is exactly the friction this avoids). Must run BEFORE any
    module-level os.environ.get() below, so config-file-only values
    (e.g. AI_MAX_TOKENS with no real env var set) actually take effect.
    """
    config_path = os.path.join(os.path.dirname(__file__), "ai_config.env")
    if not os.path.exists(config_path):
        return
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_ai_config()

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Reasoning models (e.g. self-hosted Qwen3 variants served with a
# reasoning/thinking parser) spend completion tokens on an internal
# chain-of-thought BEFORE writing the actual answer -- confirmed on a real
# local Qwen server where 500 tokens got entirely consumed by that
# reasoning step, leaving the visible `content` field empty
# (finish_reason="length") and the JSON response empty in turn. Overridable
# via AI_MAX_TOKENS (env var or ai_config.env) for models that need even
# more headroom, or less for a plain fast model where 4000 is overkill.
DEFAULT_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "4000"))

# Identical (category, condition text) should always resolve to the same
# extracted result -- without this, two RULEs in the same filing that
# happen to share byte-identical condition text (e.g. HKF1/HKF2 both
# reading "TICKETS MAY ONLY BE SOLD IN HONGKONG AND MACAU." for CAT15)
# could get genuinely DIFFERENT answers, purely from the self-hosted
# reasoning model's sampling randomness -- neither `temperature` nor
# `seed` is pinned on the request (see `_call_openai_compatible()`).
# Confirmed live, real end-to-end runs, not a hypothetical: the exact
# same CAT15 text correctly extracted "Hong Kong"/"Macau" for HKF1 in one
# run and for HKF2 in a different run, with the OTHER rule coming back
# completely blank both times -- same input, inconsistent output,
# depending purely on which call the model happened to handle well.
# Keyed on everything that actually varies the prompt EXCEPT
# fare_context/rule_id -- rule_id is shown to the model only as
# informational context (which RULE this is), never something the
# correct extraction should depend on, so two rules sharing the same
# text are expected to share the same answer.
# Deliberately process-lifetime, not reset per run: real usage is low
# volume (see CLAUDE.md -- tens of WOs/month), so unbounded growth for
# the life of one `uvicorn` process is a non-issue, and it also means
# two SEPARATE filing runs that happen to share text (e.g. resubmitting
# the same file, or another RULE using the same boilerplate clause) get
# the same consistency benefit, not just RULEs within one run.
_extraction_cache = {}


def _cache_key(spec_path, condition_text, output_fields, field_labels):
    return (
        spec_path,
        condition_text,
        tuple(output_fields),
        tuple(sorted((field_labels or {}).items())),
    )


def _normalize_condition_text(text):
    """
    Collapses whitespace-only formatting noise -- extra spaces, embedded
    line breaks, trailing whitespace -- that doesn't represent a real
    difference in what the condition text says. Confirmed real case:
    HKF1/HKF2's CAT16 "Notes" text is the exact same business content
    (identical service-fee sentence), typed with a stray line break in
    one file and not the other ("REVALIDATION/   \\nREFUND" vs
    "REVALIDATION/ REFUND") -- which, before this normalization, meant
    the two rules didn't share a cache entry and each needed its own
    real AI call even though nothing meaningful actually differed.
    Applied before both the cache key AND the prompt itself, so the
    model is never shown the stray formatting either.
    """
    if not isinstance(text, str):
        return text
    return " ".join(text.split())


def extract_with_ai(condition_text, fare_context, spec_path, output_fields, field_labels=None):
    condition_text = _normalize_condition_text(condition_text)
    category = fare_context.get("category", "?")
    rule_id = fare_context.get("rule_id", "?")
    provider = os.environ.get("AI_PROVIDER", "anthropic")

    cache_key = _cache_key(spec_path, condition_text, output_fields, field_labels)
    cached = _extraction_cache.get(cache_key)
    if cached is not None:
        usage = cached["usage"]
        run_logger.record_ai_call(
            category, rule_id, provider, cached["model"], 0.0, "cached",
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            detail="identical condition text already resolved earlier -- reused, no new call",
        )
        return dict(cached["result"])  # copy -- some callers mutate the returned dict

    spec = _load_spec(spec_path)
    prompt = _build_prompt(condition_text, fare_context, spec, output_fields, field_labels or {})

    if provider == "openai_compatible":
        base_url = os.environ.get("AI_BASE_URL")
        model = os.environ.get("AI_MODEL")
        if not base_url or not model:
            run_logger.record_ai_call(category, rule_id, provider, model or "?", 0.0, "mock",
                                       detail="AI_BASE_URL/AI_MODEL not set")
            return _mock_response(output_fields,
                                   reason="AI_PROVIDER=openai_compatible but AI_BASE_URL/AI_MODEL not set "
                                          "-- mock response, not a real AI call")
        start = time.time()
        try:
            raw, usage = _call_openai_compatible(prompt, base_url, model)
        except Exception as e:
            run_logger.record_ai_call(category, rule_id, provider, model, time.time() - start, "error", detail=str(e))
            return _mock_response(output_fields, reason=f"AI call failed ({e}) -- fell back to blank, flagged")
        run_logger.record_ai_call(category, rule_id, provider, model, time.time() - start, "ok", **usage)
    else:  # "anthropic"
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        model = os.environ.get("AI_MODEL", DEFAULT_ANTHROPIC_MODEL)
        if not api_key:
            run_logger.record_ai_call(category, rule_id, provider, model, 0.0, "mock",
                                       detail="ANTHROPIC_API_KEY not set")
            return _mock_response(output_fields,
                                   reason="No ANTHROPIC_API_KEY set -- mock response, not a real AI call")
        start = time.time()
        try:
            raw, usage = _call_claude(prompt, api_key)
        except Exception as e:
            run_logger.record_ai_call(category, rule_id, provider, model, time.time() - start, "error", detail=str(e))
            return _mock_response(output_fields, reason=f"AI call failed ({e}) -- fell back to blank, flagged")
        run_logger.record_ai_call(category, rule_id, provider, model, time.time() - start, "ok", **usage)

    try:
        parsed = _parse_json_response(raw, output_fields)
        parsed["confidence"] = "LOW"
        parsed["flag_reason"] = "AI-extracted from free text -- needs human review"
        parsed["ai_used"] = True
        # Which specific fields the AI actually populated (vs. left null
        # because the text didn't address them) -- this is what makes
        # per-CELL highlighting possible in template_writer.py instead of
        # shading the whole row. A category resolver that harvests only
        # some of these fields (e.g. CAT19 taking 5 of them) still needs
        # to recompute this against what it actually keeps -- see
        # categories/base.py's _copy_ai_fields().
        parsed["ai_fields"] = {f for f in output_fields if parsed.get(f) is not None}
        _extraction_cache[cache_key] = {"result": dict(parsed), "model": model, "usage": usage}
        return parsed
    except Exception as e:
        return _mock_response(output_fields, reason=f"Response parsing failed ({e}) -- fell back to blank, flagged")


def _load_spec(spec_path):
    with open(spec_path) as f:
        return yaml.safe_load(f)


def _build_prompt(condition_text, fare_context, spec, output_fields, field_labels):
    # Show the AI the field it's filling using the EXACT label a human
    # filer sees in the real template (e.g. "Passenger Type", "MIN Age"),
    # not our internal short key names -- this is the template-as-schema
    # part: field_labels comes straight from template_schema.py reading
    # the actual spreadsheet headers, not a hand-written description.
    field_lines = []
    for f in output_fields:
        label = field_labels.get(f)
        if label:
            field_lines.append(f'  "{f}": null   // template column label: "{label}"')
        else:
            field_lines.append(f'  "{f}": null')
    schema_block = "{\n" + ",\n".join(field_lines) + "\n}"

    return f"""You are extracting structured fare-filing data from an airline fare rule's condition text.

Category: {spec['category']}
Instruction: {spec['instruction']}

Fare context (the specific fare this condition applies to):
{json.dumps(fare_context, indent=2)}

Condition text to interpret:
\"\"\"{condition_text}\"\"\"

Output ONLY a JSON object with exactly these fields (the comment after each
one is the exact column label used in the real fare filing template -- use
it to understand what the field means). Use null for any field the text
doesn't address -- do not guess or invent values:
{schema_block}
"""


def _call_claude(prompt, api_key):
    """Returns (response_text, usage_dict)."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("AI_MODEL", DEFAULT_ANTHROPIC_MODEL)
    response = client.messages.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
    }
    return response.content[0].text, usage


def _call_openai_compatible(prompt, base_url, model):
    """
    Works against any server implementing the OpenAI chat-completions
    API -- Ollama (http://host:11434/v1), vLLM (http://host:8000/v1),
    text-generation-webui's openai extension, LM Studio, etc. This is
    how a self-hosted model (e.g. Qwen) plugs in without touching any
    other file in this project. Returns (response_text, usage_dict).
    """
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=os.environ.get("AI_API_KEY", "not-needed"))
    response = client.chat.completions.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return response.choices[0].message.content, usage


def _parse_json_response(raw_text, output_fields):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    parsed = json.loads(cleaned)
    return {f: parsed.get(f) for f in output_fields}


def _mock_response(output_fields, reason):
    entry = {f: None for f in output_fields}
    entry["confidence"] = "LOW"
    entry["flag_reason"] = reason
    entry["ai_used"] = True
    entry["ai_fields"] = set()  # nothing was actually extracted -- no real value to highlight
    return entry
