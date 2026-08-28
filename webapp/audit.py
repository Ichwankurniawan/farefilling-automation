"""
Append-only audit trail for the upload form -- who submitted which WO,
when, from where. Separate on purpose from both webapp/jobs.py's
in-memory/persisted job state (which is about tracking a job's own
progress, and can legitimately be cleaned up once a job is old -- see
the deployment runbook's still-unbuilt retention job) and each job's own
run_log.txt (diagnostics/progress for that one run, not a queryable
cross-job record). Without something like this there is currently no
answer at all to "who ran what" -- a real gap for a tool that touches
real fare-filing data, even with no authentication in place yet to tie
a submission to a real identity beyond the requesting IP.

Deliberately NOT structured logging / a database -- one append-only text
file, one line per submission, matches the project's existing style
(run_logger.py) rather than introducing a new dependency for what's
currently a low-volume internal tool. Revisit if usage or audit
requirements grow past what grep/a text editor can answer.
"""
import os
import time

AUDIT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.log")


def log_submission(job_id, wo_id, sheet_type, client_ip, filenames):
    """
    One line per submission, written the moment a job is accepted (after
    validation passes, before the worker picks it up) -- so the record
    exists even if the job itself later fails or the server restarts
    mid-run. Append-only, best-effort: a transient disk issue here
    shouldn't block a real submission over its own audit trail.
    """
    line = (
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"job={job_id} wo_id={wo_id} sheet_type={sheet_type} "
        f"client_ip={client_ip} files={list(filenames)}"
    )
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
