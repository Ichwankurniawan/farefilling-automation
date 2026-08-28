"""
Covers webapp/jobs.py's get_queue_position() -- the mechanism behind
"Queued -- N jobs ahead of you".

Deliberately does NOT go through submit_job()/the real queue.Queue --
that would require a real worker thread to actually process the job
(pipeline calls, AI calls, real files) just to set up a test scenario.
Importing webapp.jobs already has real side effects at module level
(creates webapp/uploads/, webapp/outputs/, starts a daemon worker thread
that blocks forever on an empty queue.Queue -- harmless here, since
nothing is ever put on it and it's a daemon thread) -- this test only
adds to that shared module state directly, under the same _jobs_lock the
real code uses, and cleans up after itself so tests don't leak into each
other.
"""
import contextlib

from webapp import jobs


def _make_job(status):
    return {"status": status}


@contextlib.contextmanager
def _temp_jobs_state(jobs_by_id, queue_order, current_running_job_id=None):
    """
    Installs a known _jobs / _queue_order / _current_running_job_id
    scenario for the duration of the block, then restores whatever was
    there before -- so these tests don't depend on run order or leak
    state into each other or into a real webapp instance sharing the
    same process.
    """
    with jobs._jobs_lock:
        saved_jobs = dict(jobs._jobs)
        saved_order = list(jobs._queue_order)
        saved_running = jobs._current_running_job_id

        jobs._jobs.clear()
        jobs._jobs.update(jobs_by_id)
        jobs._queue_order[:] = queue_order
        jobs._current_running_job_id = current_running_job_id
    try:
        yield
    finally:
        with jobs._jobs_lock:
            jobs._jobs.clear()
            jobs._jobs.update(saved_jobs)
            jobs._queue_order[:] = saved_order
            jobs._current_running_job_id = saved_running


def test_first_in_queue_with_nothing_running_is_position_zero():
    with _temp_jobs_state({"a": _make_job("queued")}, ["a"], current_running_job_id=None):
        assert jobs.get_queue_position("a") == 0


def test_first_in_queue_behind_a_running_job_is_position_one():
    with _temp_jobs_state({"a": _make_job("queued")}, ["a"], current_running_job_id="running-job"):
        assert jobs.get_queue_position("a") == 1


def test_second_in_queue_counts_both_the_running_job_and_the_one_ahead():
    with _temp_jobs_state(
        {"a": _make_job("queued"), "b": _make_job("queued")},
        ["a", "b"],
        current_running_job_id="running-job",
    ):
        assert jobs.get_queue_position("b") == 2


def test_non_queued_status_returns_none_position_no_longer_meaningful():
    # Once a job leaves "queued" the browser already has richer progress
    # via status/log_lines -- position stops being the relevant signal.
    for status in ("matching", "loading", "resolving", "writing", "done", "error"):
        with _temp_jobs_state({"a": _make_job(status)}, []):
            assert jobs.get_queue_position("a") is None, status


def test_unknown_job_id_returns_none():
    with _temp_jobs_state({}, []):
        assert jobs.get_queue_position("does-not-exist") is None


def test_job_missing_from_queue_order_but_still_queued_treated_as_next_in_line():
    # Real race: picked up by the worker between the status check and the
    # _queue_order lookup inside get_queue_position() itself -- ValueError
    # from .index() is caught, not left to propagate as a crash.
    with _temp_jobs_state({"a": _make_job("queued")}, [], current_running_job_id="running-job"):
        assert jobs.get_queue_position("a") == 1
