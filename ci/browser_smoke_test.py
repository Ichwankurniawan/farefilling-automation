"""
CI smoke test -- drives the real webapp/static form via a headless
browser (against a live uvicorn instance the CI job starts separately)
and confirms:

  1. Submitting an empty form shows client-side validation and makes NO
     backend request. Regression test for the actual bug found during
     manual testing: the hidden file <input> used to keep `required`,
     which browsers silently refuse to validate (can't show the native
     tooltip on a hidden field), cancelling the whole submit with zero
     visible feedback -- see webapp/static/index.html's `novalidate` +
     the JS-side validateForm().

  2. A filled-out submission actually reaches the backend: POST
     /api/jobs fires, a job is created, and it reaches a terminal state.
     Uses a synthetic blank .xlsx generated on the fly (no real pricebook
     needed) with a Rule & Tariff spec that can't match it -- expects the
     job to fail with a RULE-detection error. That's success for THIS
     test: it proves the request/response/polling plumbing works
     end-to-end, not that AI extraction works (that needs a real
     pricebook file and a reachable AI endpoint -- out of scope for a
     shared CI runner, see pipeline-regression-real-files in
     .gitlab-ci.yml).

Exit code is the pass/fail signal GitLab CI reads.
"""
import os
import sys
import tempfile

import openpyxl
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("SMOKE_TEST_BASE_URL", "http://127.0.0.1:8000")
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__))


def fail(page, name, msg):
    print(f"FAIL: {msg}")
    if page is not None:
        try:
            page.screenshot(path=os.path.join(ARTIFACT_DIR, f"failure_{name}.png"), full_page=True)
        except Exception:
            pass
    sys.exit(1)


def make_dummy_xlsx(path):
    wb = openpyxl.Workbook()
    wb.active["A1"] = "not a real pricebook -- CI smoke test fixture"
    wb.save(path)


def main():
    dummy_path = tempfile.mktemp(suffix=".xlsx")
    make_dummy_xlsx(dummy_path)

    console_errors = []
    requests_seen = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        page.on("request", lambda r: requests_seen.append((r.method, r.url)))

        page.goto(BASE_URL + "/", wait_until="networkidle")

        # ---- check 1: empty submit -> validation shown, no backend call ----
        requests_seen.clear()
        page.click("#submit-btn")
        page.wait_for_timeout(300)

        if not page.is_visible("#error-panel"):
            fail(page, "empty_submit", "empty form submit did not show the validation error panel")
        if any("/api/jobs" in url for _method, url in requests_seen):
            fail(page, "empty_submit_leaked", "empty form submit should NOT reach the backend, but it did")
        print("OK: empty form submit shows client-side validation, no backend call made")

        # ---- check 2: filled submit reaches the backend end-to-end ----
        page.fill("#wo_id", "CISMOKE1")
        page.select_option("#sheet_type", "1")
        page.fill("#rule_tariff_text", "NOPE (X1)")
        page.set_input_files("#files", dummy_path)

        requests_seen.clear()
        page.click("#submit-btn")
        page.wait_for_timeout(1500)

        if not any(method == "POST" and "/api/jobs" in url for method, url in requests_seen):
            fail(page, "no_post", f"clicking Submit on a filled form never sent POST /api/jobs. "
                                   f"Requests seen: {requests_seen}")
        print("OK: filled form submit sent POST /api/jobs")

        if console_errors:
            fail(page, "console_errors", f"unexpected browser console errors: {console_errors}")

        for _ in range(20):
            if page.is_visible("#error-panel") or page.is_visible("#manual-download"):
                break
            page.wait_for_timeout(1000)
        else:
            fail(page, "no_terminal_state", "job never reached a terminal state (error or done) within 20s")

        if not page.is_visible("#error-panel"):
            fail(page, "unexpected_success",
                 "expected the synthetic dummy file to fail RULE detection, but no error was shown "
                 "(did a real pricebook accidentally get used instead of the dummy fixture?)")

        error_text = page.text_content("#error-text") or ""
        if "rule" not in error_text.lower():
            fail(page, "wrong_error", f"expected a RULE-detection error message, got: {error_text!r}")
        print(f"OK: submission reached the backend and failed as expected: {error_text[:120]}")

        browser.close()

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
