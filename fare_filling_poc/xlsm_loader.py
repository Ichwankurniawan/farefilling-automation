"""
Loads a PricebookData instance directly from a real XLSM pricebook file
(like V1-ABC1 Type1.xlsm).

IMPORTANT: real pricebook files don't reliably start their tables at A1
(title rows, notes, blank spacer rows can appear above the actual header).
So instead of assuming "row 1 is the header", every sheet's header row is
LOCATED by scanning for known column-name keywords and picking the row
with the best match -- see find_header_row().
"""
import openpyxl
from pricebook_data import PricebookData

# Keywords used to locate each sheet's header row. Only a few distinctive
# column names are needed per sheet -- doesn't need to be exhaustive.
SHEET_KEYWORDS = {
    "Fare Rules": ["CATEGORIES", "FARE RULE CONDITIONS"],
    "CAT03-Seasonality": ["ORIGIN", "DESTINATION", "SEASONALITY"],
    "CAT04-FlightApplication": ["OUTBOUND SECTORS AND FLIGHTS", "INBOUND SECTORS AND FLIGHTS"],
    "CAT11-Blackouts": ["ORIGIN", "DESTINATION", "PERIOD Start"],
    "Output": ["Fare Class", "OW/RT"],
}

# CAT050607 has its own reader (see _read_cat050607) because it has a
# two-row header where "UNIT" repeats three times (once per ADV
# PURCHASE/MIN STAY/MAX STAY group) -- a single flat header row can't
# disambiguate that on its own.
CAT050607_SUB_HEADER_KEYWORDS = ["ADV PURCHASE", "MIN STAY", "MAX STAY"]

# CAT04-FlightApplication has its own reader for the same reason: a
# two-row header where ORIGIN/DESTINATION/FARE BASIS only exist on the
# group row above OUTBOUND/INBOUND SECTORS AND FLIGHTS -- confirmed on a
# real file where the generic single-row reader silently dropped LOC1/
# LOC2/FareClassFamily entirely (those columns are blank at the
# sub-header row, so they never became dict keys at all).
CAT04_SUB_HEADER_KEYWORDS = ["OUTBOUND SECTORS AND FLIGHTS", "INBOUND SECTORS AND FLIGHTS"]

# CAT03-Seasonality ALSO has a two-row header, same shape as CAT11-
# Blackouts' -- confirmed on a real file where the generic single-row
# reader picked the GROUP row instead of the true sub-header row: the
# group row's merged "SEASONALITY DATES" cell contains "SEASONALITY" as
# a substring, tying/beating the real sub-header row on the generic
# ["ORIGIN", "DESTINATION", "SEASONALITY"] keyword search. Effect: the
# sub-header row itself got read in as a bogus first DATA row, and
# PERIOD Start/PERIOD End/SEASONALITY never became real dict keys at all
# (they only exist on the sub-header row, which was never selected) --
# every CAT03 row came out with FareClassFamily/FirstDate/LastDate/
# SeasonType all None. Use keywords specific enough to only match the
# sub-header row.
CAT03_SUB_HEADER_KEYWORDS = ["PERIOD Start", "PERIOD End"]


def _find_sheet(wb, expected_name):
    """
    Exact sheet-name matching is too fragile in practice -- confirmed on a
    real file where "CAT03-Seasonality" is actually named "CAT03-
    Seasonality" (one extra space). Match after stripping spaces so
    formatting-only differences in the sheet name don't hide a tab that's
    genuinely present.
    """
    target = expected_name.replace(" ", "").lower()
    for name in wb.sheetnames:
        if name.replace(" ", "").lower() == target:
            return name
    return None


def _normalize_cat_number(value):
    """
    Fare Rules' CAT-number column comes through inconsistently across real
    files: sometimes a string with stray whitespace ("04 "), sometimes a
    bare float (10.0, 11.0, ...) since Excel auto-types cells without a
    leading zero as numbers instead of text. Every category resolver looks
    categories up by a zero-padded 2-digit string ("04", "10"), so without
    this, CAT04 (trailing space) and every CAT10+ (float, not string) row
    silently fails to match and the whole category falls through as
    "no row found" -- confirmed on a real file where this hid all of
    CAT04 and CAT10-33's actual condition text.
    """
    if value is None:
        return value
    if isinstance(value, float):
        return f"{int(value):02d}"
    text = str(value).strip()
    return f"{int(text):02d}" if text.isdigit() else text


def load_pricebook_from_xlsm(path, rule_id):
    wb = openpyxl.load_workbook(path, keep_vba=False, data_only=True)

    # Fare Rules' "RULE" column here actually holds the CATEGORY NUMBER
    # ("01", "02", ...) -- confirmed naming collision from earlier
    # analysis; _read_fare_rules_with_subrows() renames it to "CAT" (some
    # real files merge it into a single "RULE CATEGORIES" header cell
    # instead of separate "RULE"/"CATEGORIES" columns -- same data,
    # different header text, both accepted). It also carries that CAT
    # number forward onto sub-rows that don't repeat it themselves (e.g.
    # CAT10's "> Circle Trips") and captures their own label as SUB_ROW --
    # see that function's docstring for the real-file bug this fixes.
    fare_rules_rows = _read_fare_rules_with_subrows(wb["Fare Rules"], SHEET_KEYWORDS["Fare Rules"])

    tabs = {}
    for sheet_name in ("CAT03-Seasonality", "CAT04-FlightApplication"):
        actual_name = _find_sheet(wb, sheet_name)
        if not actual_name:
            continue
        rows = None
        if sheet_name == "CAT03-Seasonality":
            rows = _read_cat03_seasonality(wb[actual_name])
        elif sheet_name == "CAT04-FlightApplication":
            rows = _read_cat04_flight_application(wb[actual_name])
            if rows is None:
                rows = _read_cat04_flight_application_single_column(wb[actual_name])
        if rows is None:
            rows = _sheet_to_rows(wb, actual_name, SHEET_KEYWORDS[sheet_name])
        tabs[sheet_name] = rows

    # "Output" carries the real per-Fare-Class OW/RT value (1=OW, 2=RT,
    # 3=OW/RT -- confirmed) -- one row per Fare Class, NOT one per RULE,
    # so a single RULE can have several different OW/RT values across its
    # rows. See common_fields.py's _lookup_owrt() for how this gets
    # resolved into an actual field value.
    output_name = _find_sheet(wb, "Output")
    if output_name:
        tabs["Output"] = _sheet_to_rows(wb, output_name, SHEET_KEYWORDS["Output"])

    cat050607_name = _find_sheet(wb, "CAT050607")
    if cat050607_name:
        tabs["CAT050607"] = _read_cat050607(wb[cat050607_name])
    cat11_name = _find_sheet(wb, "CAT11-Blackouts")
    if cat11_name:
        tabs["CAT11-Blackouts"] = _read_cat11_blackouts(wb[cat11_name])

    filing_instructions = {}
    filing_name = _find_sheet(wb, "Filing Instructions")
    if filing_name:
        filing_instructions = _read_filing_instructions(wb[filing_name])

    return PricebookData(rule_id=rule_id, fare_rules_rows=fare_rules_rows, tabs=tabs,
                          filing_instructions=filing_instructions)


def find_header_row(ws, keywords, max_scan_rows=100):
    """
    Scans the first `max_scan_rows` rows and returns whichever row
    contains the most of the given keywords (case-insensitive substring
    match against each cell's text). This replaces the old "row 1 is
    always the header" assumption.

    max_scan_rows defaults to 100, not a smaller number -- real files can
    have substantial preamble (titles, notes, legends) before the actual
    table starts, and every sample seen so far only had 1-2 preamble rows,
    which isn't a representative stress test. Scanning further is cheap
    (header-row search only, not full data reading), so the default errs
    generous rather than risking a silent wrong-row pick on a file with
    more preamble than expected.

    On a TIE, prefers the LATER row. This matters for two-row headers
    like CAT050607's: the group row's merged cell text ("ADV PURCHASE /
    MIN STAY / MAX STAY") contains all three keywords as substrings in
    ONE cell, scoring the same as the true sub-header row below it (which
    has them in three separate cells) -- the sub-header row is the one
    we actually want, and it's always the later one in this file's layout.
    """
    normalized = [k.upper() for k in keywords]
    best_row, best_score = 1, -1
    for row in range(1, max_scan_rows + 1):
        row_values = [str(ws.cell(row=row, column=c).value or "").upper()
                       for c in range(1, ws.max_column + 1)]
        score = sum(1 for k in normalized if any(k in v for v in row_values))
        if score >= best_score:
            best_score, best_row = score, row
    return best_row


MAX_CONSECUTIVE_BLANK_ROWS = 50


def _sheet_to_rows(wb, sheet_name, keywords):
    """
    Reads every data row below the detected header into a dict. Confirmed
    on a real file (a 25,000-row "Output" tab where actual data ends at
    row 30 -- everything past it is phantom blank formatting, a very
    common real-world Excel quirk): the naive nested ws.cell(row=,
    column=) loop this used to be takes 5+ minutes (still hadn't finished
    at that point) on a sheet Excel reports as having thousands of rows,
    even though almost none of them hold real data -- which reads as the
    whole job being "stuck" from the caller's side, not just slow, since
    this happens inside the "matching"-labeled phase with no progress
    reported for the entire duration.

    Fixed two ways:
    - ws.iter_rows(values_only=True) instead of per-cell ws.cell() calls
      -- confirmed ~0.08s vs. 5+ minutes on the same real file, even
      without switching the workbook itself to read_only mode (which
      would need touching every other reader in this file that relies on
      style/merged-cell access read_only doesn't support).
    - Stops after MAX_CONSECUTIVE_BLANK_ROWS in a row -- a real signal
      that we've passed the end of actual data, not just a rare gap
      inside it (every real file's data seen so far is contiguous; a
      50-row blank run has never occurred except past the true end).
      Without this, iter_rows() alone would still walk all 25,000 rows,
      just fast rather than catastrophically slow -- this bounds it
      properly regardless of how large the phantom range is.
    """
    ws = wb[sheet_name]
    header_row = find_header_row(ws, keywords)
    headers = [ws.cell(row=header_row, column=c).value for c in range(1, ws.max_column + 1)]

    result = []
    blank_streak = 0
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row, values_only=True):
        if all(v is None for v in row):
            blank_streak += 1
            if blank_streak >= MAX_CONSECUTIVE_BLANK_ROWS:
                break
            continue
        blank_streak = 0
        result.append({headers[i]: row[i] for i in range(len(headers)) if headers[i] is not None})
    return result


def _read_fare_rules_with_subrows(ws, keywords):
    """
    Same output shape as _sheet_to_rows() for the "Fare Rules" sheet, but
    fixes two real bugs _sheet_to_rows() has on this specific sheet --
    confirmed by direct inspection of a real file, not assumed:

    1. Several categories' condition text isn't one flat cell -- it's a
       category header row ("10", "COMBINATIONS") immediately followed
       by zero or more SUB-ROWS that repeat NO category number of their
       own, just a "> <label>" text (e.g. "> Circle Trips", "> Side
       Trips") in a column between the CAT-number column and "FARE RULE
       CONDITIONS". Confirmed on CAT10, CAT15, CAT16, CAT19 in the same
       real file. _sheet_to_rows() has no carry-forward logic, so these
       sub-rows all silently land under CAT=None -- completely invisible
       to get_fare_rules_subrows(), which every one of those four
       resolvers depends on. This was masked because CAT15's Location
       fields still partly extract from its own flat condition text
       (the AI call just silently never sees the Ticketing Mode/Ticket
       Stock sub-rows), and CAT10/CAT16/CAT19 have NO other fallback --
       CAT19 (Children/Infant Discounts) came back completely empty
       despite its extraction logic being fully designed and confirmed
       correct, purely because the sub-rows it needs never reached it.

    2. The sub-row label column has NO header text of its own in the
       real file (confirmed: the header row's cell there is blank), so
       _sheet_to_rows() drops that column's content entirely -- its
       {headers[i]: row[i] ... if headers[i] is not None} comprehension
       skips any column with a None header. Located here by CONTENT
       instead (scanning for "> "-prefixed cells), same principle as
       bug #24's _find_cat_code_column() -- there's no header to trust.
    """
    header_row = find_header_row(ws, keywords)
    headers = [ws.cell(row=header_row, column=c).value for c in range(1, ws.max_column + 1)]

    cat_col_idx = next(
        (i for i, h in enumerate(headers) if h and str(h).strip().upper() in ("RULE", "RULE CATEGORIES")), None)

    sub_label_col_idx = None
    scan_limit = min(ws.max_row, header_row + 500)
    for c in range(1, ws.max_column + 1):
        for r in range(header_row + 1, scan_limit + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip().startswith(">"):
                sub_label_col_idx = c - 1
                break
        if sub_label_col_idx is not None:
            break

    result = []
    current_cat = None
    for row_idx in range(header_row + 1, ws.max_row + 1):
        row_vals = [ws.cell(row=row_idx, column=c).value for c in range(1, ws.max_column + 1)]
        if all(v is None for v in row_vals):
            continue
        row = {headers[i]: row_vals[i] for i in range(len(headers)) if headers[i] is not None}

        cat_val = row_vals[cat_col_idx] if cat_col_idx is not None else None
        sub_label = row_vals[sub_label_col_idx] if sub_label_col_idx is not None else None

        # Pop the raw "RULE"/"RULE CATEGORIES" key here (same rename
        # load_pricebook_from_xlsm used to do after the fact) -- must
        # happen unconditionally, including on sub-rows where it's
        # present but None, otherwise a stale None would sit alongside
        # our carried-forward "CAT" below under a different key name.
        row.pop("RULE", None)
        row.pop("RULE CATEGORIES", None)

        if cat_val is not None:
            current_cat = _normalize_cat_number(cat_val)
        elif sub_label and str(sub_label).strip().startswith(">") and current_cat is not None:
            # A sub-row of whichever category header was most recently
            # seen above it -- carry that category's number forward, and
            # expose the sub-row's own label (leading "> " stripped) as
            # SUB_ROW, matching what get_fare_rules_subrows() expects.
            row["SUB_ROW"] = str(sub_label).strip().lstrip(">").strip()

        if current_cat is not None:
            row["CAT"] = current_cat
        result.append(row)
    return result


def _read_cat050607(ws):
    """
    CAT050607 has a two-row header:
        Row N (group):    ORIGIN | DESTINATION | FARE BASIS... | ADV PURCHASE / MIN STAY / MAX STAY (merged, spans 6 cols)
        Row N+1 (sub):     (blank)| (blank)     | (blank)       | ADV PURCHASE | UNIT | MIN STAY | UNIT | MAX STAY | UNIT

    ORIGIN/DESTINATION/FARE BASIS only exist on the group row (the
    sub-header row is blank under them) -- so for each column we use the
    sub-header label if present, falling back to the group row's label
    otherwise. Each "UNIT" column is paired POSITIONALLY with the value
    column immediately to its left (e.g. the UNIT right after "MIN STAY"
    becomes "MIN STAY UNIT") -- that's reliable here because the
    sub-header row's own left-to-right order is what carries the meaning;
    the group row's shared merged label can't disambiguate which "UNIT"
    belongs to which pair.
    """
    sub_row = find_header_row(ws, CAT050607_SUB_HEADER_KEYWORDS)
    group_row = sub_row - 1
    max_col = ws.max_column

    headers = []
    last_value_label = None
    for c in range(1, max_col + 1):
        sub_label = ws.cell(row=sub_row, column=c).value
        group_label = ws.cell(row=group_row, column=c).value if group_row >= 1 else None

        if sub_label is None:
            headers.append(group_label)  # ORIGIN/DESTINATION/FARE BASIS live only here
        elif str(sub_label).strip().upper() == "UNIT":
            headers.append(f"{last_value_label} UNIT" if last_value_label else "UNIT")
        else:
            headers.append(sub_label)
            last_value_label = sub_label

    result = []
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=c).value for c in range(1, max_col + 1)]
        if all(v is None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(len(headers)) if headers[i] is not None})
    return result


def _read_cat04_flight_application(ws):
    """
    Same two-row-header shape and reasoning as _read_cat050607() (see its
    docstring): ORIGIN/DESTINATION/FARE BASIS live only on the group row,
    OUTBOUND/INBOUND SECTORS AND FLIGHTS on the sub-header row below it.

    Some real files DON'T have this two-row shape at all -- confirmed one
    with a single "FLIGHT APPLICATION" column and IF/THEN conditional
    text covering both directions in one blob, no OUTBOUND/INBOUND split.
    Returns None in that case rather than guessing at a different shape;
    the caller falls back to the generic single-row reader.
    """
    sub_row = find_header_row(ws, CAT04_SUB_HEADER_KEYWORDS)
    row_text = " ".join(
        str(ws.cell(row=sub_row, column=c).value or "") for c in range(1, ws.max_column + 1)
    ).upper()
    if not any(kw in row_text for kw in CAT04_SUB_HEADER_KEYWORDS):
        return None  # not this shape

    group_row = sub_row - 1
    max_col = ws.max_column

    headers = []
    for c in range(1, max_col + 1):
        sub_label = ws.cell(row=sub_row, column=c).value
        group_label = ws.cell(row=group_row, column=c).value if group_row >= 1 else None
        headers.append(sub_label if sub_label is not None else group_label)

    result = []
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=c).value for c in range(1, max_col + 1)]
        if all(v is None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(len(headers)) if headers[i] is not None})
    return result


def _read_cat04_flight_application_single_column(ws):
    """
    A THIRD real shape for this tab, confirmed on a real file: a single
    "FLIGHT APPLICATION" header (no OUTBOUND/INBOUND split at all) whose
    data rows carry a filler sub-label ("ONLY VALID ON") directly under
    the header, with the actual IF/THEN condition text one column to the
    right of it -- confirmed by row inspection (header row has ORIGIN/
    DESTINATION/FARE BASIS/FLIGHT APPLICATION as a normal single-row
    header; several blank spacer rows below it are normal, real data
    rows follow further down, same as any other tab).

    Returns rows with a "FLIGHT APPLICATION TEXT" key (instead of the
    OUTBOUND/INBOUND SECTORS AND FLIGHTS keys the two other shapes use)
    -- Cat04Resolver applies that one text to both O and I since this
    shape has no direction split to read from. Returns None if this
    file doesn't have a "FLIGHT APPLICATION" column at all, so the
    caller can fall back further.
    """
    header_row = find_header_row(ws, ["ORIGIN", "DESTINATION", "FLIGHT APPLICATION"])
    max_col = ws.max_column

    flight_app_col = None
    other_cols = {}
    for c in range(1, max_col + 1):
        label = ws.cell(row=header_row, column=c).value
        if not label:
            continue
        label_str = str(label).strip()
        if label_str.upper() == "FLIGHT APPLICATION":
            flight_app_col = c
        else:
            other_cols[c] = label_str

    if flight_app_col is None:
        return None

    text_col = flight_app_col + 1

    result = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        row_vals = {other_cols[c]: ws.cell(row=row_idx, column=c).value for c in other_cols}
        text = ws.cell(row=row_idx, column=text_col).value
        if all(v is None for v in row_vals.values()) and text is None:
            continue
        row_vals["FLIGHT APPLICATION TEXT"] = text
        result.append(row_vals)
    return result


def _read_filing_instructions(ws):
    """
    "Filing Instructions" is key-value shaped, not row-based like every
    other sheet: column B = field header (e.g. "Sales From/To"), column C
    = first value, column D = second value (only present for from/to
    pairs). Returns {field_header: value_or_(value1,value2)_tuple}.
    """
    header_row = find_header_row(ws, ["Field Header", "Field Values"])
    result = {}
    for row_idx in range(header_row + 1, ws.max_row + 1):
        field_header = ws.cell(row=row_idx, column=2).value
        if not field_header:
            continue
        val1 = ws.cell(row=row_idx, column=3).value
        val2 = ws.cell(row=row_idx, column=4).value
        result[field_header] = (val1, val2) if val2 is not None else val1
    return result


def _read_cat11_blackouts(ws):
    """
    CAT11-Blackouts ALSO has a two-row header, discovered after CAT11 was
    already coded assuming a flat single-row header (bug, deferred until
    this batch update):
        Row N (group):    ORIGIN | DESTINATION | FARE BASIS... | BLACKOUT DATE (merged, spans 2 cols)
        Row N+1 (sub):     (blank)| (blank)     | (blank)       | PERIOD Start (DD-MMM-YY) | PERIOD End (DD-MMM-YY)

    Simpler than CAT050607's reader -- only one group, so no repeated
    column name needs positional disambiguation. ORIGIN/DESTINATION/FARE
    BASIS fall back to the group row same as CAT050607.
    """
    sub_row = find_header_row(ws, ["PERIOD Start"])
    group_row = sub_row - 1
    max_col = ws.max_column

    headers = []
    for c in range(1, max_col + 1):
        sub_label = ws.cell(row=sub_row, column=c).value
        group_label = ws.cell(row=group_row, column=c).value if group_row >= 1 else None
        headers.append(sub_label if sub_label is not None else group_label)

    result = []
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=c).value for c in range(1, max_col + 1)]
        if all(v is None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(len(headers)) if headers[i] is not None})
    return result


def _read_cat03_seasonality(ws):
    """
    Same two-row-header shape and reasoning as _read_cat11_blackouts()
    (see its docstring):
        Row N (group):    ORIGIN | DESTINATION | FARE BASIS... | SEASONALITY DATES (merged, spans 3 cols)
        Row N+1 (sub):     (blank)| (blank)     | (blank)       | SEASONALITY | PERIOD Start (DD-MMM-YY) | PERIOD End (DD-MMM-YY)

    ORIGIN/DESTINATION/FARE BASIS fall back to the group row, same as
    CAT11's reader. Located via CAT03_SUB_HEADER_KEYWORDS (specific
    enough to only match the true sub-header row -- see its comment).
    """
    sub_row = find_header_row(ws, CAT03_SUB_HEADER_KEYWORDS)
    group_row = sub_row - 1
    max_col = ws.max_column

    headers = []
    for c in range(1, max_col + 1):
        sub_label = ws.cell(row=sub_row, column=c).value
        group_label = ws.cell(row=group_row, column=c).value if group_row >= 1 else None
        headers.append(sub_label if sub_label is not None else group_label)

    result = []
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        row = [ws.cell(row=row_idx, column=c).value for c in range(1, max_col + 1)]
        if all(v is None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(len(headers)) if headers[i] is not None})
    return result


# ---------------------------------------------------------------------------
# Type 2/3 loading -- structurally different from Type 1 (see
# pricebook_data_type2.py). Both "Fare Rules" and "Fare Rule(POO)" share
# the same reading logic; the POO sheet is located by KEYWORD ("POO" as a
# substring of the sheet name), not an exact name match, since naming
# varies ("Fare Rule(POO)" vs "Fare Rules POO" etc.).
# ---------------------------------------------------------------------------
from pricebook_data_type2 import PricebookDataType2

FARE_RULES_TYPE2_KEYWORDS = ["Rule Categories", "Same as Base Reference Fare"]


def _find_owrt_sheet(wb):
    """
    Locates the sheet holding the real per-fare-class OW/RT data for Type
    2/3 pricebooks -- this is a SEPARATE sheet from "Fare Rules"/"...POO",
    carrying the raw output data (one row per market/fare class), NOT the
    category condition text. Its name varies wildly across real files
    ("Edifact_Filing_CDM_A7J8F", "NDC_Filing_CDM_A7J8F", "Faresheet ") --
    no naming convention to key off of, so it's located by CONTENT
    (scanning every sheet for a literal "RT/OW" header cell) rather than
    by name or fixed position, even though it has always been sheet 0 on
    every real sample seen so far.
    """
    for name in wb.sheetnames:
        ws = wb[name]
        header_row = find_header_row(ws, ["RT/OW"], max_scan_rows=20)
        row_values = [str(ws.cell(row=header_row, column=c).value or "").strip().upper()
                      for c in range(1, ws.max_column + 1)]
        if "RT/OW" in row_values:
            return name
    return None


def _read_owrt_rows(wb):
    """
    Returns the raw rows from the OW/RT data sheet (see _find_owrt_sheet),
    or [] if no such sheet was found. Value domain confirmed from real
    files: the "RT/OW" column is always literally "RT/OW" (both
    directions permitted) in every sample seen so far -- "OW" (one-way
    only) is documented as the other possible value but hasn't been seen
    yet. See common_fields.py's _lookup_owrt_type23() for the
    text-to-template-value normalization.
    """
    sheet_name = _find_owrt_sheet(wb)
    if not sheet_name:
        return []
    return _sheet_to_rows(wb, sheet_name, ["RT/OW"])


def load_pricebook_type2(path, rule_id):
    """Returns (main_pricebook, poo_pricebook) -- poo_pricebook is None if
    no sheet with "POO" in its name exists in this file."""
    wb = openpyxl.load_workbook(path, keep_vba=False, data_only=True)

    main_sheet_name = wb.sheetnames[0]  # "Fare Rules" is always sheet 1 in our samples
    for name in wb.sheetnames:
        if "poo" not in name.lower() and "fare rule" in name.lower():
            main_sheet_name = name
            break

    poo_sheet_name = next((n for n in wb.sheetnames if "poo" in n.lower()), None)
    owrt_rows = _read_owrt_rows(wb)

    main_pb = PricebookDataType2(rule_id, _read_fare_rules_type2(wb[main_sheet_name]), owrt_rows=owrt_rows)
    poo_pb = None
    if poo_sheet_name:
        poo_pb = PricebookDataType2(rule_id, _read_fare_rule_poo(wb[poo_sheet_name]), owrt_rows=owrt_rows)

    return main_pb, poo_pb


from pricebook_data_type2 import _normalize_category_key


def _looks_like_cat_label(value):
    s = str(value).strip().upper() if value is not None else ""
    return s.startswith("CAT ") or s == "RBD"


def _find_cat_code_column(ws, header_row):
    """
    Finds the column that actually holds category codes ("CAT 01", "RBD",
    ...) by CONTENT, not by trusting the header row's own label position.
    Confirmed necessary on a real file where the header row's "Rule
    Categories" label sat one column to the right of where the data
    itself actually starts (header row's own first cell was blank) --
    while every OTHER header label (Same as Base / override text / Alt
    Gen Rule) was correctly positioned. A blanket column-shift would have
    broken those, so only this one column is re-derived from content.
    """
    sample_rows = range(header_row + 1, min(header_row + 20, ws.max_row + 1))
    best_col, best_hits = None, 0
    for c in range(1, min(ws.max_column, 10) + 1):
        hits = sum(1 for r in sample_rows if _looks_like_cat_label(ws.cell(row=r, column=c).value))
        if hits > best_hits:
            best_col, best_hits = c, hits
    return best_col


def _read_fare_rules_type2(ws):
    """
    Supports both single-row categories (most) and multi-row/sub-row
    categories (confirmed for CAT10: Circle Trips / Side Trips /
    End-on-End / Half Round Trip / etc, each its own row under one
    "CAT 10" label that only appears on the FIRST sub-row) -- so the
    category label is carried forward across blank-label rows, same
    principle as Type 1's SUB_ROW handling.
    """
    header_row = find_header_row(ws, FARE_RULES_TYPE2_KEYWORDS)
    headers = [ws.cell(row=header_row, column=c).value for c in range(1, ws.max_column + 1)]

    cat_col = _find_cat_code_column(ws, header_row)
    # Description has no reliable header label to fall back on (the real
    # file that exposed this had NO "Category Description" header at all
    # -- see _find_cat_code_column) -- but it's consistently the column
    # immediately after the category code in every sample and real file
    # seen so far, so derive it positionally instead of by header text.
    desc_col = cat_col + 1 if cat_col else None

    categories = {}
    current_cat = None
    for row_idx in range(header_row + 1, ws.max_row + 1):
        values = {headers[i]: ws.cell(row=row_idx, column=c).value
                   for i, c in enumerate(range(1, ws.max_column + 1)) if headers[i] is not None}
        cat_label_raw = str(ws.cell(row=row_idx, column=cat_col).value or "").strip() if cat_col else ""

        if cat_label_raw.upper().startswith("CAT "):
            current_cat = cat_label_raw
        elif cat_label_raw:
            # a non-CAT, non-blank label (e.g. "RBD") -- not a real
            # category and has no sub-rows of its own
            current_cat = None
            continue

        if current_cat is None:
            continue

        description = ws.cell(row=row_idx, column=desc_col).value if desc_col else values.get("Category Description")
        same_as_base = values.get("Same as Base Reference Fare\n(Yes/No/NA) ?")
        override_text = values.get('If "NO", amend Base Rule as follows:')
        alt_gen_rule = values.get("For HO/TCS:\nAlt Gen Rule IPRG")
        if not any([description, same_as_base, override_text, alt_gen_rule]):
            continue  # fully blank spacer row

        categories.setdefault(current_cat, []).append({
            "description": description,
            "same_as_base": same_as_base,
            "override_text": override_text,
            "alt_gen_rule": alt_gen_rule,
        })
    return categories


def _read_fare_rule_poo(ws):
    """
    The value column's header is DYNAMIC (e.g. "POO boardpoint -
    SIN/JKT/KUL/PEN/HAN/SGN", varies by file) -- located by a fixed
    sub-label instead of a fixed group name. Two sub-label styles
    confirmed so far: "For Info Only" (Type 2-style POO sheets) and
    "Same as Base Rule OR Amend Base Rule as indicated" (Type 3-style POO
    sheets, reusing the same label the main Type 3 sheet uses) -- without
    matching both, value_col silently stays None, every row's poo_value
    comes back empty, and the pipeline can't tell "FOLLOW BASE FARE" from
    real override text -- confirmed on a real file where this sent EVERY
    category to AI instead of just the ones that actually needed it. Same
    carry-forward logic as _read_fare_rules_type2 for multi-row categories
    (confirmed CAT10 has sub-rows in Fare Rule(POO) too).
    """
    sub_row = find_header_row(ws, ["For Info Only", "Same as Base Rule", "IPRG Rule"])
    max_col = ws.max_column

    value_col, iprg_col = None, None
    for c in range(1, max_col + 1):
        val = ws.cell(row=sub_row, column=c).value
        val_lower = str(val).lower() if val else ""
        if "for info only" in val_lower or "same as base rule" in val_lower:
            value_col = c
        if "iprg rule" in val_lower:
            iprg_col = c

    categories = {}
    current_cat = None
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        cat_raw = ws.cell(row=row_idx, column=1).value
        cat_raw_str = str(cat_raw).strip() if cat_raw is not None else ""
        description = ws.cell(row=row_idx, column=2).value
        poo_value = ws.cell(row=row_idx, column=value_col).value if value_col else None
        alt_gen_rule = ws.cell(row=row_idx, column=iprg_col).value if iprg_col else None

        if cat_raw_str:
            current_cat = _normalize_category_key(cat_raw_str) if any(ch.isdigit() for ch in cat_raw_str) else None
            if current_cat is None:
                continue  # non-category label row

        if current_cat is None:
            continue
        if not any([description, poo_value, alt_gen_rule]):
            continue  # fully blank spacer row

        categories.setdefault(current_cat, []).append({
            "description": description,
            "poo_value": poo_value,
            "alt_gen_rule": alt_gen_rule,
        })
    return categories


# ---------------------------------------------------------------------------
# Type 3 loading. Confirmed from real screenshots: structurally similar to
# Type 2, EXCEPT the main "Fare Rules"-equivalent sheet has ONE combined
# column ("Same as Base Rule OR Amend Base Rule as indicated") instead of
# Type 2's two separate columns (Yes/No/NA flag + override text). The POO
# sheet's structure is IDENTICAL to Type 2's POO sheet (same "For Info
# Only"/"IPRG Rule" shape) -- reuses _read_fare_rule_poo() unchanged.
# ---------------------------------------------------------------------------

def load_pricebook_type3(path, rule_id):
    """Returns (main_pricebook, poo_pricebook) -- same shape as
    load_pricebook_type2(), since the synthesized row dicts match Type 2's
    {same_as_base, override_text, alt_gen_rule} shape (see
    _synthesize_same_as_base below) -- every Type 2/3 resolver method
    already written for Type 2 works unchanged for Type 3."""
    wb = openpyxl.load_workbook(path, keep_vba=False, data_only=True)

    main_sheet_name = wb.sheetnames[0]
    for name in wb.sheetnames:
        if "poo" not in name.lower() and "fare rule" in name.lower():
            main_sheet_name = name
            break

    poo_sheet_name = next((n for n in wb.sheetnames if "poo" in n.lower()), None)
    owrt_rows = _read_owrt_rows(wb)

    main_pb = PricebookDataType2(rule_id, _read_fare_rules_type3(wb[main_sheet_name]), owrt_rows=owrt_rows)
    poo_pb = None
    if poo_sheet_name:
        poo_pb = PricebookDataType2(rule_id, _read_fare_rule_poo(wb[poo_sheet_name]), owrt_rows=owrt_rows)

    return main_pb, poo_pb


def _read_fare_rules_type3(ws):
    """
    Header value column is DYNAMIC too (e.g. "ex-CN" in the real sample,
    confirmed to vary per file same as POO's "POO boardpoint - X") --
    located by the fixed "Same as Base Rule OR Amend Base Rule as
    indicated" sub-label, not by the dynamic group name. Same
    carry-forward logic as Type 2's reader for multi-row categories
    (CAT10 confirmed to have sub-rows in Type 3 too, with its own real
    example: "WC61/.../WC69" rule codes instead of Type 2's "WC21/.../WC29").
    """
    sub_row = find_header_row(ws, ["Same as Base Rule", "IPRG Rule"])
    max_col = ws.max_column

    value_col, iprg_col = None, None
    for c in range(1, max_col + 1):
        val = ws.cell(row=sub_row, column=c).value
        if val and "same as base rule" in str(val).lower():
            value_col = c
        if val and "iprg rule" in str(val).lower():
            iprg_col = c

    categories = {}
    current_cat = None
    for row_idx in range(sub_row + 1, ws.max_row + 1):
        cat_raw = ws.cell(row=row_idx, column=1).value
        cat_raw_str = str(cat_raw).strip() if cat_raw is not None else ""
        description = ws.cell(row=row_idx, column=2).value
        combined_value = ws.cell(row=row_idx, column=value_col).value if value_col else None
        iprg = ws.cell(row=row_idx, column=iprg_col).value if iprg_col else None

        if cat_raw_str.upper().startswith("CAT "):
            current_cat = cat_raw_str
        elif cat_raw_str:
            current_cat = None  # e.g. "RBD" -- not a real category
            continue

        if current_cat is None:
            continue
        if not any([description, combined_value, iprg]):
            continue  # fully blank spacer row

        same_as_base, override_text = _synthesize_same_as_base(combined_value)
        categories.setdefault(current_cat, []).append({
            "description": description,
            "same_as_base": same_as_base,
            "override_text": override_text,
            "alt_gen_rule": iprg,
        })
    return categories


def _synthesize_same_as_base(combined_value):
    """
    Type 3 has ONE combined column instead of Type 2's two separate
    columns. If it says "FOLLOW ..." or "NOT APPLICABLE"/"NA", that's
    equivalent to Type 2's Yes/NA (nothing to extract); otherwise the
    column's content IS the override text directly, equivalent to Type
    2's 'No' + override text. Synthesizing into Type 2's shape lets every
    Type 2/3 resolver method work unchanged for Type 3.
    """
    text = (combined_value or "").strip()
    upper = text.upper()
    if not text or upper.startswith("FOLLOW") or upper in ("NOT APPLICABLE", "NA"):
        return "Yes", None
    return "No", text
