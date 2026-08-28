"""
Covers webapp/ratelimit.py's exact boundary -- formalizes the direct
unit test already run by hand when this was built.
"""
import importlib

from webapp import ratelimit


def fresh_ratelimit():
    """Each test gets a clean slate -- the module's state is a plain
    dict, not something with a reset() of its own."""
    importlib.reload(ratelimit)
    return ratelimit


def test_exactly_max_submissions_allowed_then_blocked():
    rl = fresh_ratelimit()
    ip = "1.2.3.4"
    for _ in range(rl.MAX_SUBMISSIONS):
        assert rl.check_and_record(ip) is None
    # One more over the limit must be blocked, with a positive retry hint.
    retry_after = rl.check_and_record(ip)
    assert retry_after is not None
    assert retry_after > 0


def test_different_ip_is_fully_independent():
    rl = fresh_ratelimit()
    for _ in range(rl.MAX_SUBMISSIONS):
        rl.check_and_record("1.1.1.1")
    assert rl.check_and_record("1.1.1.1") is not None  # over limit
    assert rl.check_and_record("9.9.9.9") is None  # untouched by the other IP's usage
