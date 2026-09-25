"""
Lightweight shared progress/AI-call logger.

Deliberately kept separate from the pipeline's data output (the
pipeline_output_*.json dump and the written .xlsx) -- this module only
ever prints to the console and, if configured, appends to its own .txt
log file. Nothing it writes ever goes near the actual filing data.

Used by pipeline.py (per-category progress) and ai_engine.py (AI call
timing + token usage). run_new_filing.py calls set_log_file() once at
the start of a run and log_summary() at the end.
"""
import os
import time

_log_file_path = None
_run_started_at = None
_ai_calls = []  # list of dicts, one per AI call attempt (real or mock)


def set_log_file(path):
    """Call once at the start of a run. Truncates any existing file."""
    global _log_file_path, _run_started_at, _ai_calls
    _log_file_path = path
    _run_started_at = time.time()
    _ai_calls = []
    with open(_log_file_path, "w", encoding="utf-8") as f:
        f.write(f"=== Fare filing run log -- started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")


def log(msg):
    """Prints a timestamped line to the console and (if configured) the log file."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _log_file_path:
        with open(_log_file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def record_ai_call(category, rule_id, provider, model, elapsed_s, status,
                    prompt_tokens=None, completion_tokens=None, total_tokens=None, detail=None):
    """
    Records one AI call attempt (status: "ok", "error", "mock", or
    "cached" -- ai_engine.py's extraction cache reused an earlier result
    for identical condition text instead of calling the model again) for
    the end-of-run summary, and logs it immediately so progress is
    visible while a slow (e.g. reasoning-model) call is still running.
    """
    _ai_calls.append({
        "category": category, "rule_id": rule_id, "provider": provider, "model": model,
        "elapsed_s": elapsed_s, "status": status,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens,
    })

    token_part = ""
    if total_tokens is not None:
        token_part = f" | tokens(prompt/completion/total)={prompt_tokens}/{completion_tokens}/{total_tokens}"
    status_part = {"ok": "OK", "error": "FAILED", "mock": "MOCK (no real call)",
                   "cached": "CACHED (reused, no new call)"}.get(status, status)
    detail_part = f" | {detail}" if detail else ""
    log(f"[AI] {category} rule={rule_id} provider={provider} model={model} "
        f"-> {status_part} in {elapsed_s:.2f}s{token_part}{detail_part}")


def log_summary():
    """Prints (and logs) total run time and an AI-call token/timing summary."""
    total_elapsed = time.time() - _run_started_at if _run_started_at else None

    real_calls = [c for c in _ai_calls if c["status"] == "ok"]
    mock_calls = [c for c in _ai_calls if c["status"] == "mock"]
    failed_calls = [c for c in _ai_calls if c["status"] == "error"]
    cached_calls = [c for c in _ai_calls if c["status"] == "cached"]
    ai_time = sum(c["elapsed_s"] for c in _ai_calls)
    total_tokens = sum(c["total_tokens"] or 0 for c in real_calls)
    prompt_tokens = sum(c["prompt_tokens"] or 0 for c in real_calls)
    completion_tokens = sum(c["completion_tokens"] or 0 for c in real_calls)
    # What the cache hits would have cost, had they not been reused -- not
    # counted in the real totals above (no tokens were actually spent).
    cached_tokens_saved = sum(c["total_tokens"] or 0 for c in cached_calls)

    log("=" * 60)
    log("RUN SUMMARY")
    if total_elapsed is not None:
        log(f"  Total run time: {total_elapsed:.2f}s")
    log(f"  AI calls: {len(_ai_calls)} total "
        f"({len(real_calls)} real, {len(mock_calls)} mock, {len(failed_calls)} failed, "
        f"{len(cached_calls)} cached)")
    if _ai_calls:
        log(f"  Time spent in AI calls: {ai_time:.2f}s")
    if real_calls:
        log(f"  Token usage (real calls only): prompt={prompt_tokens} "
            f"completion={completion_tokens} total={total_tokens}")
    if cached_calls:
        log(f"  Cache reuse: {len(cached_calls)} call(s) skipped, ~{cached_tokens_saved} tokens saved "
            f"(identical condition text already resolved earlier)")
    for c in failed_calls:
        log(f"  FAILED: {c['category']} rule={c['rule_id']} ({c['elapsed_s']:.2f}s)")
    log("=" * 60)
    if _log_file_path:
        print(f"Full log written to {_log_file_path}")
