"""
Background job runner for the upload-form web app.

Wraps the exact same pipeline steps run_new_filing.py already runs
(intake_matcher.match_files_to_rules -> load_pricebook_* -> run_pipeline*
-> write_to_template*), just driven from an HTTP submission instead of
CLI flags, and reporting progress into an in-memory job record instead of
stdout.

Deliberately single-worker (one job processed at a time): run_logger.py
is module-level global state (set_log_file/log/record_ai_call all write
to shared module variables), so running two pipeline jobs concurrently in
different threads would interleave/corrupt each other's log. A FIFO
queue + one worker thread is the simplest correct fix for a v1 internal
tool -- a WO's AI-heavy run already takes minutes, so jobs queueing
briefly behind each other is an acceptable tradeoff, not a real
bottleneck at expected usage volume.
"""
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "fare_filling_poc")
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "template", "SQ Fare Filling Template.xlsx")

RULE_TARIFF_GROUP_RE = re.compile(r"([A-Za-z0-9]+)\s*\(\s*([^)]+?)\s*\)")

# job_id -> job dict. Fine as a plain dict for a single-process internal
# tool; each job is only ever touched by the worker thread (while
# running) or read-only by request handlers (via .copy()).
_jobs = {}
_jobs_lock = threading.Lock()
_queue = queue.Queue()

STATUS_ORDER = ["queued", "matching", "loading", "resolving", "writing", "done", "error"]
TERMINAL_STATUSES = {"done", "error"}
STATE_FILENAME = "state.json"

STATUS_LABEL = {
    "queued": "Queued",
    "matching": "Matching files to fare rules",
    "loading": "Reading pricebook data from the matched file(s)",
    "resolving": "Resolving fare categories (this can take a few minutes if AI is needed)",
    "writing": "Writing the completed filing",
    "done": "Done",
    "error": "Error",
}


def _new_job_record(job_id, wo_id, sheet_type, rule_tariff_text, saved_files):
    return {
        "id": job_id,
        "wo_id": wo_id,
        "sheet_type": sheet_type,
        "rule_tariff_text": rule_tariff_text,
        "files": saved_files,
        "status": "queued",
        "status_label": STATUS_LABEL["queued"],
        "message": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "output_path": None,
        "output_filename": None,
        "log_lines": [],
    }


def submit_job(wo_id, sheet_type, rule_tariff_text, upload_tmp_paths):
    """
    upload_tmp_paths: list of (original_filename, saved_path) already
    written to disk by the request handler (under a job-specific folder).
    Returns the new job_id.
    """
    job_id = uuid.uuid4().hex[:12]
    job = _new_job_record(job_id, wo_id, sheet_type, rule_tariff_text, upload_tmp_paths)
    with _jobs_lock:
        _jobs[job_id] = job
    _persist(job_id)
    _queue.put(job_id)
    return job_id


def get_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _state_path(job_id):
    return os.path.join(UPLOAD_DIR, job_id, STATE_FILENAME)


def _persist(job_id):
    """
    Writes the job's current state to disk -- job history previously
    vanished entirely on a restart (a real gap hit twice in this
    project's own testing: a restart mid-job left the browser polling a
    job id that returned 404 forever, no way to tell what happened).
    Atomic write (temp file + os.replace, which is atomic on both
    Windows and POSIX within the same filesystem) so a crash exactly
    mid-write never leaves a corrupt state.json behind. Best-effort: a
    transient disk error here shouldn't crash a real job over its own
    resilience layer, so failures are swallowed, not raised.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
        snapshot = dict(job) if job else None
    if snapshot is None:
        return
    path = _state_path(job_id)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
        os.replace(tmp_path, path)
    except OSError:
        pass


def _load_jobs_from_disk():
    """
    Called once at import time (server startup) -- restores job history
    across a restart instead of starting with a blank slate every time.

    A job that was genuinely in-progress (not done/error) when the
    process stopped can't just resume where it left off -- the thread
    running it, and everything in its local variables (the
    partially-built pipeline output, the pricebook objects), is gone.
    Marking it as a clear, explained failure is the honest option;
    silently leaving it at e.g. "resolving" forever with no worker
    actually processing it would be worse than the gap this fixes --
    indistinguishable from the original stuck-job problem this project
    already spent real effort diagnosing once (see xlsm_loader.py's
    _sheet_to_rows() fix and its CLAUDE.md writeup).
    """
    if not os.path.isdir(UPLOAD_DIR):
        return
    restored = 0
    interrupted = 0
    for job_id in os.listdir(UPLOAD_DIR):
        path = _state_path(job_id)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("status") not in TERMINAL_STATUSES:
            note = "This job was interrupted by a server restart before it finished. Please resubmit."
            job["status"] = "error"
            job["status_label"] = STATUS_LABEL["error"]
            job["error"] = note
            job["message"] = note
            job.setdefault("log_lines", []).append(note)
            interrupted += 1
        # JSON round-trips job["files"] entries (originally (name, path)
        # tuples) as plain lists -- restore tuples so every existing
        # `for (_name, p) in job["files"]` unpack site keeps working
        # unchanged, whether the job was just created or reloaded.
        job["files"] = [tuple(entry) for entry in job.get("files", [])]
        _jobs[job_id] = job
        restored += 1
    if restored:
        print(f"[jobs] Restored {restored} job(s) from disk ({interrupted} marked interrupted by restart)", flush=True)


def _set_status(job_id, status, message=None):
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = status
        job["status_label"] = STATUS_LABEL.get(status, status)
        if message:
            job["message"] = message
            job["log_lines"].append(message)
        job["updated_at"] = time.time()
    _persist(job_id)


def _run_job(job_id):
    job = get_job(job_id)
    wo_id = job["wo_id"]
    sheet_type = job["sheet_type"]
    rule_tariff_text = job["rule_tariff_text"]
    file_paths = [p for (_name, p) in job["files"]]

    try:
        import run_logger
        from intake_matcher import match_files_to_rules

        job_log_path = os.path.join(UPLOAD_DIR, job_id, "run_log.txt")
        run_logger.set_log_file(job_log_path)
        run_logger.log(f"Starting run: sheet_type={sheet_type} wo_id={wo_id}")

        _set_status(job_id, "matching", "Matching uploaded files to their fare rule...")
        try:
            matched = match_files_to_rules(file_paths, rule_tariff_text)
        except ValueError as e:
            _fail(job_id, f"Could not match files to Rule & Tariff: {e}")
            return
        run_logger.log(f"Matched files: {[f['rule'] for f in matched]}")

        # Real gap found via a real stuck job: this loading step used to
        # run entirely under the "matching" label, which was misleading
        # even on a healthy run (matching itself is done by this point --
        # see xlsm_loader.py's _sheet_to_rows() fix for the actual
        # performance bug that made one real file's load take 5+ minutes
        # instead of ~7s, with zero progress visible the whole time).
        _set_status(job_id, "loading", "Reading pricebook data from the matched file(s)...")

        anchor_rows = []
        pricebook_lookup = {}
        for f in matched:
            rule = f["rule"]
            pricebook_name = os.path.splitext(os.path.basename(f["path"]))[0]
            if sheet_type == 1:
                from xlsm_loader import load_pricebook_from_xlsm
                pricebook_lookup[rule] = load_pricebook_from_xlsm(f["path"], rule)
            elif sheet_type == 2:
                from xlsm_loader import load_pricebook_type2
                pricebook_lookup[rule] = load_pricebook_type2(f["path"], rule)
            else:
                from xlsm_loader import load_pricebook_type3
                pricebook_lookup[rule] = load_pricebook_type3(f["path"], rule)
            for tariff in f["tariffs"]:
                anchor_rows.append({
                    "RULE": rule, "TARIFF": tariff,
                    "PRICEBOOK_NAME": pricebook_name, "sheet_type": sheet_type,
                })

        _set_status(job_id, "resolving", "Resolving every fare category (AI is used only where deterministic rules don't match)...")

        output_path = os.path.join(OUTPUT_DIR, f"SQ Fare Filing_{wo_id}_Type{sheet_type}_{job_id}.xlsx")

        if sheet_type == 1:
            from pipeline import run_pipeline
            from template_writer import write_to_template

            output = run_pipeline(anchor_rows, pricebook_lookup)

            _set_status(job_id, "writing", "Writing the completed filing into the template...")
            write_to_template(
                template_path=TEMPLATE_PATH,
                pipeline_output=output,
                anchor_rows=anchor_rows,
                output_path=output_path,
                wo_id=wo_id,
            )
        else:
            from pipeline import run_pipeline_type2_3
            from template_writer import write_to_template_type2

            output_main, output_poo = run_pipeline_type2_3(anchor_rows, pricebook_lookup)

            _set_status(job_id, "writing", "Writing the completed filing into the template...")
            write_to_template_type2(
                template_path=TEMPLATE_PATH,
                output_main=output_main,
                output_poo=output_poo,
                anchor_rows=anchor_rows,
                output_path=output_path,
                wo_id=wo_id,
            )

        run_logger.log(f"Done. Wrote {output_path}")
        run_logger.log_summary()

        with _jobs_lock:
            j = _jobs[job_id]
            j["output_path"] = output_path
            j["output_filename"] = os.path.basename(output_path)
        _set_status(job_id, "done", "Filing completed.")

    except Exception as e:
        # The full traceback is genuinely useful for diagnosing a real bug,
        # but dumping it into the browser's error panel is unreadable for
        # whoever's actually running the form -- and the single most likely
        # real-world cause of an unexpected crash here is a mismatched
        # Filing Classification Type (e.g. a Type 2 file loaded as Type 1
        # expects a "Fare Rules" sheet that a Type 2/3 file may not have
        # under that exact name, and similar structural mismatches). Show
        # a plain, actionable message; keep the traceback in the run log
        # (and stderr, via traceback.print_exc()) for real debugging.
        traceback.print_exc()
        try:
            import run_logger
            run_logger.log(f"FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        except Exception:
            pass
        friendly = (
            "This filing could not be processed. The most common cause is the uploaded "
            "file not matching the selected Filing Classification Type -- double-check "
            "that the file is really a Type " + str(sheet_type) + " pricebook. "
            f"(Technical detail: {type(e).__name__}: {e})"
        )
        _fail(job_id, friendly)


def _fail(job_id, message):
    with _jobs_lock:
        job = _jobs[job_id]
        job["error"] = message
    _set_status(job_id, "error", message)


def _worker_loop():
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        except Exception as e:
            _fail(job_id, f"Unhandled worker error: {e}")
        finally:
            _queue.task_done()


_load_jobs_from_disk()

_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()
