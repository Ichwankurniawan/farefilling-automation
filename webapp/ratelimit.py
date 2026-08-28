"""
A minimal per-IP submission throttle for POST /api/jobs -- deliberately
NOT rate-limiting GET /api/jobs/{id} (the frontend legitimately polls
that every 2s per active job; throttling it would break normal use).

With no authentication in place (see CLAUDE.md's webapp known-limitations),
nothing else stops one client -- accidental (a stuck retry loop, a script
gone wrong) or deliberate -- from submitting far more jobs than any real
usage pattern needs. That matters more here than in a typical API: the
job queue is single-worker by design (see jobs.py), so one client
submitting a burst of jobs doesn't just cost that client time, it pushes
every OTHER real submission behind all of them, for as long as each of
those jobs takes to run (minutes, not milliseconds).

Deliberately a plain in-memory sliding window, not a library (no new
dependency, matches the project's existing style -- see audit.py) --
proportionate to a single-process, single-worker, low-volume internal
tool. Resets on restart, which is fine: nothing here is meant to survive
a restart, it's just pacing within one running process's lifetime.
"""
import threading
import time

# ~35 WOs/month overall (see the ROI numbers this project's earlier
# review was grounded in) is roughly 1-2/day in real usage -- 5
# submissions per 10 minutes per IP is generous headroom above any
# legitimate real pattern (including a user resubmitting after fixing a
# typo) while still bounding a runaway client to a small, bounded head
# start over everyone else in the queue, not an unbounded one.
MAX_SUBMISSIONS = 5
WINDOW_SECONDS = 10 * 60

_lock = threading.Lock()
_submissions_by_ip: dict[str, list[float]] = {}  # ip -> [timestamp, ...], pruned lazily on each check


def check_and_record(client_ip: str) -> int | None:
    """
    Returns None if this submission is allowed (and records it towards
    the window), or a (retry_after_seconds) int if the client is over
    the limit -- the caller decides what HTTP response that becomes.
    """
    now = time.time()
    with _lock:
        timestamps = _submissions_by_ip.setdefault(client_ip, [])
        cutoff = now - WINDOW_SECONDS
        timestamps[:] = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= MAX_SUBMISSIONS:
            retry_after = int(timestamps[0] + WINDOW_SECONDS - now) + 1
            return retry_after

        timestamps.append(now)
        return None
