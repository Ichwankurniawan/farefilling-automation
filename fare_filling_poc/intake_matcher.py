"""
Matches uploaded pricebook files to the RULE(s) typed into the upload
form's single free-text "Rule & Tariff" field -- e.g.
"HKF1 (FBRA23P), HKF2 (FBRA3P, FBRINPV)" alongside N uploaded files, with
NO per-file field telling the backend which file belongs to which RULE.

CONFIRMED unreliable, both ruled out:
  - Filename matching: works for HKF1/HKF2 (RULE literally in the
    filename), but fails on real files already in use -- the Cargolux
    CDM file's RULE is "3J8F", but its filename only contains the SMT
    Corp ID "A7J8F" ("3J8F" isn't even a substring of "A7J8F").
  - Upload order matching Nth-file-to-Nth-spec: silent and unrecoverable
    if a user uploads files in a different order than they typed the
    specs -- no way to detect the mismatch, and the result is a wrong
    RULE/TARIFF assigned to a real fare filing.

Instead: read each file's OWN internal RULE value (the "ATPCO Rule
No." / "ATPCO Rule Number :" / "NDC ATPCO Rule No." cell -- label text
varies, but "ATPCO RULE" is a consistent substring across every real
variant confirmed so far: Type 1/2/3, Edifact/NDC) and match that
against the typed specs. Any mismatch, duplicate, or unmatched item is
a hard error -- never guessed.
"""
import re
import openpyxl

# Every real label variant seen contains this substring, confirmed across
# all 6 real sample files (Type 1/2/3, Edifact/NDC):
#   "ATPCO Rule Number :", "ATPCO Rule No.", "NDC ATPCO Rule No.",
#   "ATPCO Rule Number (NDC) :"
LABEL_KEYWORD = "ATPCO RULE"

# Where the label cell was actually found, per real file (confirmed):
#   Type 1: "Filing Instructions" sheet, value directly to the RIGHT.
#           (The "Fare Rules" sheet also has the label, but its value
#           cell is blank on that particular sheet -- scanning multiple
#           sheets/positions, not just one, is why this still works.)
#   Type 2/3: the main data sheet (name varies -- "Edifact_Filing_...",
#           "NDC_Filing_...", "Faresheet ") -- value directly to the
#           RIGHT, same row.
# Scanning a bounded area across every sheet (not hardcoding which sheet)
# means this doesn't need separate Type 1 vs Type 2/3 logic at all.
MAX_SHEETS = 10
MAX_ROWS = 20
MAX_COLS = 15

RULE_GROUP_RE = re.compile(r'([A-Za-z0-9]+)\s*\(\s*([^)]+?)\s*\)')


def _looks_like_rule_code(value):
    """A plausible RULE code: short, no internal spaces, not a label
    fragment like "Distribution :" (which would fail on the space)."""
    if value is None:
        return False
    s = str(value).strip()
    return bool(s) and " " not in s and 2 <= len(s) <= 10


def detect_rule_from_file(path):
    """
    Scans the file for its own internal RULE identifier. Tries every
    plausible neighbor of a matching label cell (value can sit directly
    right, two cells right if the label spans a merged cell, or one row
    below -- all three shapes confirmed on real files) and returns the
    first match found; if OTHER matches turn up elsewhere in the same
    file and disagree with the first, raises rather than silently
    trusting whichever was found first.

    Returns the detected RULE string, or None if no label was found at
    all -- callers should treat that as "couldn't determine", not guess.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    found = []
    for sheet_name in wb.sheetnames[:MAX_SHEETS]:
        ws = wb[sheet_name]
        max_r = min(ws.max_row or 0, MAX_ROWS)
        max_c = min(ws.max_column or 0, MAX_COLS)
        for r in range(1, max_r + 1):
            for c in range(1, max_c + 1):
                cell_val = ws.cell(row=r, column=c).value
                if not cell_val or LABEL_KEYWORD not in str(cell_val).upper():
                    continue
                candidates = [
                    ws.cell(row=r, column=c + 1).value,
                    ws.cell(row=r, column=c + 2).value,
                    ws.cell(row=r + 1, column=c).value,
                ]
                for cand in candidates:
                    if _looks_like_rule_code(cand):
                        found.append((sheet_name, r, c, str(cand).strip()))
                        break
    wb.close()

    if not found:
        return None

    values = {f[3].upper() for f in found}
    if len(values) > 1:
        raise ValueError(
            f"{path!r}: found multiple DIFFERENT internal RULE values in the same file "
            f"({sorted(values)}) -- refusing to guess which is correct. Locations: {found}"
        )
    return found[0][3]


def _parse_rule_tariff_text(text):
    """
    Parses the form's free-text field into {RULE: [TARIFF, ...]}.
    Finds every "NAME(...)" group independently via regex rather than
    splitting on commas first -- the field mixes two different comma
    meanings ("HKF1 (FBRA23P), HKF2 (FBRA3P, FBRINPV)": the comma between
    groups separates RULEs, the comma inside the second group separates
    TARIFFs for the SAME rule), so a naive split-on-comma would wrongly
    cut "FBRA3P, FBRINPV" into two different RULEs' worth of tariffs.
    """
    specs = {}
    for m in RULE_GROUP_RE.finditer(text):
        rule = m.group(1).strip().upper()
        tariffs = [t.strip() for t in m.group(2).split(",") if t.strip()]
        if not tariffs:
            continue
        specs[rule] = tariffs
    return specs


def match_files_to_rules(file_paths, rule_tariff_text):
    """
    Matches each uploaded file to the RULE it belongs to via each file's
    OWN internal RULE value -- see module docstring for why filename/
    order matching were ruled out. Raises ValueError with a specific,
    actionable message on any ambiguity:
      - a file's internal RULE couldn't be detected at all
      - two files internally claim the same RULE
      - a file's internal RULE wasn't typed in the Rule & Tariff field
      - a typed RULE has no matching uploaded file

    Returns: list of {"path": ..., "rule": ..., "tariffs": [...]}, in
    the same shape run_new_filing.py's explicit --file/--rule-tariff
    pairing already produces -- drop-in for the rest of the pipeline.
    """
    specs = _parse_rule_tariff_text(rule_tariff_text)
    if not specs:
        raise ValueError(
            f"Could not parse any RULE(TARIFF) groups out of the Rule & Tariff field: {rule_tariff_text!r}"
        )

    detected = {}
    for path in file_paths:
        rule = detect_rule_from_file(path)
        if rule is None:
            raise ValueError(
                f"Could not detect a RULE inside {path!r} -- no 'ATPCO Rule No.'-style cell found "
                f"in the first {MAX_SHEETS} sheets. Refusing to guess; check the file."
            )
        rule = rule.upper()
        if rule in detected:
            raise ValueError(
                f"Both {detected[rule]!r} and {path!r} internally claim RULE {rule!r} -- "
                f"can't have two uploaded files for the same RULE in one submission."
            )
        detected[rule] = path

    unmatched_files = set(detected) - set(specs)
    unmatched_specs = set(specs) - set(detected)
    if unmatched_files:
        raise ValueError(
            "These uploaded file(s) have an internal RULE that wasn't typed in the Rule & Tariff "
            f"field: {[(r, detected[r]) for r in sorted(unmatched_files)]}"
        )
    if unmatched_specs:
        raise ValueError(
            f"These typed RULE(s) have no matching uploaded file: {sorted(unmatched_specs)}"
        )

    return [{"path": detected[rule], "rule": rule, "tariffs": tariffs} for rule, tariffs in specs.items()]
