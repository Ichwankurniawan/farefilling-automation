"""
Writes pipeline.run_pipeline() output into the REAL uploaded template
(SQ_Fare_Filling_Template.xlsx, sheet "(FINAL TEMPLATE) CAT 1-CAT 33 w").

Where each field lives (column letters, start rows) is NOT defined here
-- that's template_columns.py, imported wholesale below via `from
template_columns import *`. This file is the writing LOGIC only: row
shifting/capacity, style preservation, per-cell AI highlighting, output
value normalization, and the actual per-category write sequence. See
template_columns.py's own docstring for how those column letters were
established (read directly from the template with openpyxl, not guessed)
and confirmed layout notes (merged header/title rows vs. non-merged data
rows, the "Table" = "NEW" default that only applies to some categories).
"""

import datetime
import re
from copy import copy
from openpyxl.styles import PatternFill

import run_logger
from template_columns import *  # noqa: F401,F403 -- CATxx_COLS/CATxx_START_ROW/COLS_BY_CATEGORY etc., used throughout this file's write sequence

# ---- output normalization ----
#
# Root cause of the "inconsistent output formatting" bug (dates, case):
# every value written here comes either straight from a real pricebook
# cell (no house style enforced across different filers/years -- a date
# might be a real Excel date-typed cell in one file and free-typed text
# like "01APR26" in another) or from an AI extraction (ai_specs/*.yaml
# never told the model what date format or case convention to use, so
# it free-forms it per call). Every category resolver's .upper() calls
# only normalize case for INTERNAL matching/comparison -- never what
# actually gets stored in entry[field] for writing. This was the single
# write chokepoint (both paths converge here), so it's the single fix
# point too, rather than needing to patch ~26 category resolver files.

# Every field across every category's COLS map that holds a date value
# (confirmed exhaustively via `grep -noE '"[A-Za-z0-9]*(Date|OnAfter|
# OnBefore)[A-Za-z0-9]*"' template_writer.py` against this file's own
# COLS_BY_CATEGORY definitions -- 10 fields, 4 categories).
DATE_FIELDS = {
    "FirstDate", "LastDate",                                   # CAT03
    "Date1", "Date2",                                          # CAT11
    "OnAfterCommence", "OnBeforeCommence",                     # CAT14
    "ReservationMustBeOnAfter", "ReservationMustBeOnBefore",   # CAT15
    "TicketMustBeIssuedOnAfter", "TicketMustBeIssuedOnBefore",  # CAT15
}
DATE_NUMBER_FORMAT = "dd-mmm-yy"  # e.g. 01-Apr-26 -- explicit user decision

# Fields deliberately EXEMPT from the uppercase pass: identifiers meant
# to stay exactly as-typed for traceability back to their real source,
# not fare-filing codes. PRICEBOOK NAME is the uploaded file's own
# basename (see common_fields.py) -- uppercasing it would make it harder
# to visually match an output row back to the real file on disk.
NO_UPPERCASE_FIELDS = {"PRICEBOOK NAME"}

_MONTH_LOOKUP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_DATE_TEXT_RE = re.compile(r'^\s*(\d{1,2})[-\s]?([A-Za-z]{3,9})[-\s]?(\d{2,4})\s*$')
# AI extraction has no fixed output format (see the module-level note
# above) -- confirmed by real use, not assumed: the same pipeline run
# that exercises this path produced "2017-10-01" (ISO) from one AI call
# while other fields came back "01-OCT-17" (DD-MMM-YY) elsewhere in the
# very same file. Both input shapes need to parse successfully even
# though the OUTPUT is always normalized to DATE_NUMBER_FORMAT.
_DATE_ISO_RE = re.compile(r'^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$')


def _parse_date_value(value):
    """
    Normalizes any date-shaped value this pipeline might produce -- a
    real datetime.date/datetime (from an Excel date-typed source cell)
    or free text in whatever separator/case/order the source pricebook
    or an AI extraction happened to use ("01APR26", "1-Apr-2026",
    "01 APR 2026", ISO "2026-04-01") -- into a real datetime.date.
    Returns None if the text genuinely can't be parsed as a date, so the
    caller can fall back to writing the original value rather than
    silently losing it.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value)
    iso = _DATE_ISO_RE.match(text)
    if iso:
        year_s, month_s, day_s = iso.groups()
        try:
            return datetime.date(int(year_s), int(month_s), int(day_s))
        except ValueError:
            return None

    m = _DATE_TEXT_RE.match(text)
    if not m:
        return None
    day_s, mon_s, year_s = m.groups()
    month = _MONTH_LOOKUP.get(mon_s.upper()[:4]) or _MONTH_LOOKUP.get(mon_s.upper()[:3])
    if month is None:
        return None
    year = int(year_s)
    if year < 100:
        year += 2000 if year < 70 else 1900  # "26" -> 2026, "95" -> 1995
    try:
        return datetime.date(year, month, int(day_s))
    except ValueError:
        return None


def _normalize_output_value(field, value):
    """
    Applied at the single write chokepoint (_write_block, below) --
    covers every category and both the deterministic and AI-extracted
    paths, since both converge here. Returns (value_to_write,
    number_format_or_None).
    """
    if field in DATE_FIELDS:
        parsed = _parse_date_value(value)
        if parsed is not None:
            return parsed, DATE_NUMBER_FORMAT
        # Couldn't parse -- write the original value rather than
        # silently dropping it (a visibly-unnormalized date beats a
        # real date that vanished), but flag it so it's not mistaken
        # for a successfully normalized one.
        run_logger.log(f"[format] Could not parse {field}={value!r} as a date -- left as-is")
        return value, None
    if isinstance(value, str) and field not in NO_UPPERCASE_FIELDS:
        return value.upper(), None
    return value, None

# Any row where a resolver set entry["ai_used"] = True gets this fill
# applied across the whole row -- per-row granularity (not per-cell) per
# project decision: simpler, less code to touch, good enough for a loader
# to know "this row needs review" without pinpointing the exact field.
AI_USED_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")


def _shift_rows_down(ws, insert_at, amount):
    """
    Reliable replacement for ws.insert_rows(), which was found to silently
    drop cell values on this file (likely due to the many merged cells and
    comments elsewhere in the sheet -- a known rough edge in openpyxl).

    This does the shift manually: unmerge any merged range at/below
    insert_at, copy every cell's value downward bottom-up (so we never
    overwrite a cell before reading it), then re-merge the shifted ranges
    at their new position. Note: this preserves VALUES and merge
    structure, but not per-cell comments below the insertion point --
    acceptable for now since comments aren't part of the data we're
    filling in, but worth knowing before using this on a file where
    comments below row ~40 matter.
    """
    max_row, max_col = ws.max_row, ws.max_column

    all_ranges = list(ws.merged_cells.ranges)
    # Ranges entirely at/below insert_at: unmerge, shift down, re-merge whole.
    merges_to_shift = [r for r in all_ranges if r.min_row >= insert_at]
    # Ranges that straddle the insertion point (start above insert_at, end
    # at/below it) -- these can't be cleanly shifted (part of the range
    # stays put, part would move), so just unmerge them and leave them
    # unmerged. This happens when a template has multi-row merged header
    # cells sitting right at a category's row-capacity boundary -- without
    # this, the shift loop below hits a read-only MergedCell and crashes.
    straddling_merges = [r for r in all_ranges if r.min_row < insert_at <= r.max_row]

    for r in merges_to_shift + straddling_merges:
        ws.unmerge_cells(str(r))

    for row in range(max_row, insert_at - 1, -1):
        for col in range(1, max_col + 1):
            src = ws.cell(row=row, column=col)
            dst = ws.cell(row=row + amount, column=col)
            dst.value = src.value
            dst._style = copy(src._style)
            src.value = None

    for r in merges_to_shift:
        ws.merge_cells(start_row=r.min_row + amount, start_column=r.min_col,
                        end_row=r.max_row + amount, end_column=r.max_col)


def _ensure_capacity(ws, start_row, needed_rows, template_default=3):
    if needed_rows <= template_default:
        return 0
    extra = needed_rows - template_default
    _shift_rows_down(ws, start_row + template_default, extra)
    return extra


def _write_block(ws, rows, columns, start_row, max_col=90, no_col="A"):
    """
    Writes `rows` starting at `start_row`. Before writing, captures the
    FULL-WIDTH cell style (font, fill, border, alignment, number format)
    from `start_row` itself -- which is always one of the template's
    original, untouched example rows at this point (row-shifting only
    ever moves rows AFTER start_row + template_default, never the
    example rows themselves) -- and applies that style to every column
    of every row we write. Without this, new rows keep whatever leftover
    formatting happened to occupy that position after a shift (e.g. a
    dark header band), which is what caused the "messed up rows" bug.

    no_col: which column holds the row's own sequence number. Almost
    always "A", but CAT10's Qualifying Tables 106/107 number their own
    rows in column P instead (they're offset blocks starting at P, not A).

    AI highlighting is per-CELL, not per-row: only the specific field(s)
    a row's AI call actually populated get AI_USED_FILL, via
    row["ai_fields"] (a set of field names -- see ai_engine.py's
    extract_with_ai() and categories/base.py's _copy_ai_fields()).
    Common fields (PRICEBOOK NAME, RULE, TARIFF, AltGenTariff, AltGenRule,
    OW/RT) are never in ai_fields -- they're always deterministic, in
    every category -- so they're never highlighted regardless of what
    else in the row came from AI.
    """
    style_cache = [copy(ws.cell(row=start_row, column=c)._style) for c in range(1, max_col + 1)]

    for i, row in enumerate(rows):
        excel_row = start_row + i
        ai_fields = row.get("ai_fields")
        # Defensive fallback, not a path any current resolver actually
        # exercises (every ai_used=True entry traces back to
        # extract_with_ai(), which always sets ai_fields now -- confirmed
        # by inspection of every AI call site in categories/*.py and
        # pipeline.py's _ai_fallback_entry()): if something ever sets
        # ai_used=True without going through ai_fields, fall back to the
        # old whole-row behavior rather than silently highlighting nothing.
        if ai_fields is None:
            ai_fields = set(columns) if row.get("ai_used") else set()

        for c in range(1, max_col + 1):
            ws.cell(row=excel_row, column=c)._style = style_cache[c - 1]

        ws[f"{no_col}{excel_row}"] = i + 1
        for field, col_letter in columns.items():
            if field == "NO":
                continue
            value = row.get(field)
            if value is not None:
                normalized, number_format = _normalize_output_value(field, value)
                cell = ws[f"{col_letter}{excel_row}"]
                cell.value = normalized
                if number_format:
                    cell.number_format = number_format
                if field in ai_fields:
                    cell.fill = AI_USED_FILL


def _strip_validations_and_images(ws):
    """
    The original template has 92 data validation ranges (dropdown lists,
    e.g. "Valid On,Not Valid On") and 8 embedded images, ALL anchored to
    fixed row positions. _shift_rows_down() only moves cell values and
    styles -- it never touches these, so once enough rows get inserted
    (for categories needing more than the template's 3-row default
    capacity), dropdowns and images end up sitting on whatever content
    happens to occupy their original row position now, which is usually
    unrelated. Rather than trying to re-anchor 92+8 objects correctly
    through multiple rounds of shifting, we just remove them up front --
    this is a generated OUTPUT file for filing data, not something a
    human needs to interactively pick dropdown values in.
    """
    ws.data_validations.dataValidation = []
    if hasattr(ws, "_images"):
        ws._images = []


def _write_rule_tariff_table(ws, anchor_rows, start_row, max_col=90):
    offset = _ensure_capacity(ws, start_row, len(anchor_rows))
    style_cache = [copy(ws.cell(row=start_row, column=c)._style) for c in range(1, max_col + 1)]
    for i, anchor in enumerate(anchor_rows):
        r = start_row + i
        for c in range(1, max_col + 1):
            ws.cell(row=r, column=c)._style = style_cache[c - 1]
        ws[f"A{r}"] = i + 1
        ws[f"B{r}"] = anchor["RULE"]
        ws[f"C{r}"] = anchor["TARIFF"]
    return offset


def _assign_global_no_and_link_carrier(cat04_rows, carrier_rows):
    from collections import defaultdict

    for i, row in enumerate(cat04_rows):
        row["_global_no"] = i + 1

    groups = defaultdict(list)
    for row in cat04_rows:
        groups[(row["RULE"], row["TARIFF"])].append(row)

    lookup = {}
    for (rule, tariff), grouped in groups.items():
        for local_idx, row in enumerate(grouped):
            lookup[(rule, tariff, local_idx)] = row["_global_no"]

    for crow in carrier_rows:
        key = (crow["RULE"], crow["TARIFF"], crow.get("CAT4_ID_local_ref"))
        crow["_CAT4_ID"] = lookup.get(key)


def write_to_template(template_path, pipeline_output, anchor_rows, output_path, wo_id=None):
    import openpyxl
    wb = openpyxl.load_workbook(template_path)

    # BUGFIX: the sheet named "...CAT 1-CAT 33 w" is HIDDEN in the original
    # template -- writing to it means the data never shows up when the file
    # is opened normally, since Excel/LibreOffice display the sheet named
    # "...CAT 1-CAT 33 " (no trailing "w") by default, which was never
    # touched. Target the visible one; fall back to the "w" name only if
    # this particular workbook doesn't have a visible variant (e.g. a
    # single-sheet export like the version re-uploaded for this fix).
    sheet_name = "(FINAL TEMPLATE) CAT 1-CAT 33 "
    if sheet_name not in wb.sheetnames:
        sheet_name = "(FINAL TEMPLATE) CAT 1-CAT 33 w"
    ws = wb[sheet_name]
    if ws.sheet_state != "visible":
        ws.sheet_state = "visible"  # make sure whatever we write is actually seen
    ws.title = "OUTPUT"  # renamed from the template's own long working title, per user request

    if wo_id is not None:
        ws["B1"] = wo_id  # confirmed real cell: A1="FID (WO ID):" label, B1=the value itself

    _write_pipeline_output_to_sheet(ws, pipeline_output, anchor_rows)

    wb.save(output_path)
    return output_path


def write_to_template_type2(template_path, output_main, output_poo, anchor_rows, output_path, wo_id=None):
    """
    Type 2/3 variant: writes output_main into the normal visible sheet,
    and (if output_poo is non-empty, i.e. a Fare Rule(POO) sheet existed
    in the input) DUPLICATES that sheet -- via wb.copy_worksheet(), same
    column layout reused entirely since the template itself is identical
    -- and writes output_poo into the copy. Both sheets get their own
    row-shifting/validation-cleanup independently. wo_id, if given, is
    written to BOTH sheets' B1 (each is its own standalone filing page).
    """
    import openpyxl
    wb = openpyxl.load_workbook(template_path)

    sheet_name = "(FINAL TEMPLATE) CAT 1-CAT 33 "
    if sheet_name not in wb.sheetnames:
        sheet_name = "(FINAL TEMPLATE) CAT 1-CAT 33 w"
    ws_main = wb[sheet_name]
    if ws_main.sheet_state != "visible":
        ws_main.sheet_state = "visible"

    if output_poo:
        ws_poo = wb.copy_worksheet(ws_main)
        ws_poo.title = "OUTPUT(POO)"  # renamed from "CAT 1-CAT 33 (POO)" per user request
        ws_poo.sheet_state = "visible"
        if wo_id is not None:
            ws_poo["B1"] = wo_id
        _write_pipeline_output_to_sheet(ws_poo, output_poo, anchor_rows)

    # renamed AFTER copy_worksheet() -- copy_worksheet() reads the source
    # sheet's own current title to derive the copy's default name, so
    # renaming ws_main first would make the POO copy start from "OUTPUT"
    # instead of the original template title (harmless either way here
    # since ws_poo.title is set explicitly right after, but kept in this
    # order to avoid relying on that).
    ws_main.title = "OUTPUT"
    if wo_id is not None:
        ws_main["B1"] = wo_id
    _write_pipeline_output_to_sheet(ws_main, output_main, anchor_rows)

    wb.save(output_path)
    return output_path


def _write_pipeline_output_to_sheet(ws, pipeline_output, anchor_rows):
    _strip_validations_and_images(ws)

    cumulative_offset = 0
    cumulative_offset += _write_rule_tariff_table(ws, anchor_rows, RULE_TARIFF_START_ROW)

    if "CAT01" in pipeline_output:
        rows = pipeline_output["CAT01"]
        start = CAT01_START_ROW + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, CAT01_COLS, start)

    if "CAT02" in pipeline_output:
        rows = pipeline_output["CAT02"]
        for row in rows:
            row.setdefault("Table", "NEW")
        start = CAT02_START_ROW + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, CAT02_COLS, start)

    if "CAT03" in pipeline_output:
        rows = pipeline_output["CAT03"]
        for row in rows:
            row.setdefault("Table", "NEW")
        start = CAT03_START_ROW + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, CAT03_COLS, start)

    if "CAT04" in pipeline_output:
        cat04_rows = pipeline_output["CAT04"]
        for row in cat04_rows:
            row.setdefault("Table", "NEW")
        carrier_rows = pipeline_output.get("CAT04_CarrierTableNo1", [])
        _assign_global_no_and_link_carrier(cat04_rows, carrier_rows)

        start = CAT04_START_ROW + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(cat04_rows))
        _write_block(ws, cat04_rows, CAT04_COLS, start)

        carrier_start = CARRIER1_START_ROW + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, carrier_start, len(carrier_rows))
        carrier_style_cache = [copy(ws.cell(row=carrier_start, column=c)._style) for c in range(1, 91)]
        for i, crow in enumerate(carrier_rows):
            r = carrier_start + i
            for c in range(1, 91):
                ws.cell(row=r, column=c)._style = carrier_style_cache[c - 1]
            ws[f"X{r}"] = i + 1
            ws[f"V{r}"] = crow.get("_CAT4_ID")
            ws[f"W{r}"] = crow.get("OI")
            ws[f"Z{r}"] = crow.get("OperatingCarrier")
            ws[f"AA{r}"] = crow.get("FlightNumber1")

    # CAT05 onward: generic loop instead of repeating the CAT01-04 pattern
    # by hand each time -- this is what was MISSING before (resolvers
    # existed for CAT05-08, but this function never wrote them, which is
    # why they showed up empty in the output file despite the pipeline
    # JSON having the data). Add each new simple category's (COLS,
    # START_ROW, needs_table_default) here going forward.
    # IMPORTANT: processing order here MUST match the original template's
    # top-to-bottom row order, because cumulative_offset only accounts for
    # shifts caused by categories processed SO FAR. Qualifying Tables
    # 106/107 sit physically between CAT10 and CAT11 in the real template
    # -- writing them after CAT11-19 (as an earlier version of this code
    # did) applies shifts from categories that come AFTER them in the
    # file, over-shifting their position into unrelated merged cells.
    # Bug found via a MergedCell write crash once CAT11-19 were added.
    SIMPLE_CATEGORIES_PART1 = [
        ("CAT05", CAT05_COLS, CAT05_START_ROW, False),
        ("CAT06", CAT06_COLS, CAT06_START_ROW, False),
        ("CAT07", CAT07_COLS, CAT07_START_ROW, False),
        ("CAT08", CAT08_COLS, CAT08_START_ROW, True),
        ("CAT09", CAT09_COLS, CAT09_START_ROW, False),
        ("CAT10", CAT10_COLS, CAT10_START_ROW, False),
    ]
    for cat_name, cols, start_row, needs_table_default in SIMPLE_CATEGORIES_PART1:
        if cat_name not in pipeline_output:
            continue
        rows = pipeline_output[cat_name]
        if needs_table_default:
            for row in rows:
                row.setdefault("Table", "NEW")
        if cat_name == "CAT10":
            # Table 103 mirrors table 102 -- see the CAT10_COLS comment
            # above for why. Done here (write time), not in the resolver,
            # so it applies uniformly to both the main sheet and the POO
            # sheet's independently-resolved CircleTripPermitted value,
            # and never touches CAT10's AI schema (output_fields) at all.
            for row in rows:
                row.setdefault("CircleTrip2PlusPermitted", row.get("CircleTripPermitted"))
                # The mirrored cell needs the SAME "needs review" highlight
                # as its source when that source was AI-derived -- found by
                # testing, not assumed: without this, table 103 silently
                # shows an AI-derived value with no visual flag at all,
                # which reads as MORE certain than table 102's identical,
                # correctly-highlighted value right next to it.
                ai_fields = row.get("ai_fields")
                if ai_fields and "CircleTripPermitted" in ai_fields:
                    ai_fields.add("CircleTrip2PlusPermitted")
        start = start_row + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, cols, start)

    # CAT10's Qualifying Tables 106/107 -- physically between CAT10 and
    # CAT11 in the original template, so they must be processed here, not
    # after CAT11-19.
    for table_key, cols, start_row in [
        ("CAT10_QualifyingTable106CarrierTable", TABLE106_COLS, TABLE106_START_ROW),
        ("CAT10_QualifyingTable107TariffRuleTable", TABLE107_COLS, TABLE107_START_ROW),
    ]:
        if table_key not in pipeline_output:
            continue
        rows = pipeline_output[table_key]
        start = start_row + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, cols, start, no_col="P")

    SIMPLE_CATEGORIES_PART2 = [
        ("CAT11", CAT11_COLS, CAT11_START_ROW, True),
        ("CAT12", CAT12_COLS, CAT12_START_ROW, True),
        ("CAT13", CAT13_COLS, CAT13_START_ROW, False),
        ("CAT14", CAT14_COLS, CAT14_START_ROW, True),
        ("CAT15", CAT15_COLS, CAT15_START_ROW, True),
        ("CAT16", CAT16_COLS, CAT16_START_ROW, False),
        ("CAT17", CAT17_COLS, CAT17_START_ROW, True),
        ("CAT18", CAT18_COLS, CAT18_START_ROW, True),
        ("CAT19", CAT19_COLS, CAT19_START_ROW, True),
        ("CAT20", CAT20_COLS, CAT20_START_ROW, True),
        ("CAT21", CAT21_COLS, CAT21_START_ROW, True),
        ("CAT22", CAT22_COLS, CAT22_START_ROW, True),
        ("CAT23", CAT23_COLS, CAT23_START_ROW, False),
        ("CAT26", CAT26_COLS, CAT26_START_ROW, False),
        ("CAT27", CAT27_COLS, CAT27_START_ROW, False),
        ("CAT28", CAT28_COLS, CAT28_START_ROW, False),
        ("CAT29", CAT29_COLS, CAT29_START_ROW, False),
        ("CAT31", CAT31_COLS, CAT31_START_ROW, True),
        ("CAT33", CAT33_COLS, CAT33_START_ROW, False),
    ]
    for cat_name, cols, start_row, needs_table_default in SIMPLE_CATEGORIES_PART2:
        if cat_name not in pipeline_output:
            continue
        rows = pipeline_output[cat_name]
        if needs_table_default:
            for row in rows:
                row.setdefault("Table", "NEW")
        start = start_row + cumulative_offset
        cumulative_offset += _ensure_capacity(ws, start, len(rows))
        _write_block(ws, rows, cols, start)
