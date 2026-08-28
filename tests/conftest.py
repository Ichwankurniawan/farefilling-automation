"""
Makes fare_filling_poc/ and webapp/ importable as plain top-level modules
under pytest, matching the sys.path.insert() pattern every real entry
point in this project already uses (run_new_filing.py, webapp/jobs.py) --
neither is set up as an installed/importable package, by design (no
setup.py/pyproject.toml exists), so tests need the same path setup
rather than a different, parallel convention.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "fare_filling_poc")

for path in (PROJECT_ROOT, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
