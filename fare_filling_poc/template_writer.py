"""
Writes pipeline.run_pipeline() output into the REAL uploaded template
(SQ_Fare_Filling_Template.xlsx, sheet "(FINAL TEMPLATE) CAT 1-CAT 33 w").

Column letters below were read directly from the template with openpyxl,
not guessed -- see the header rows for each category block. Header rows
and title rows are merged cells; every data row (13+, 21+, 29+, 37+, 45+)
is NOT merged, so writing cell-by-cell is safe.

Confirmed from the template itself (useful new info beyond what was in
the DataMapping doc): "Table" = "NEW" is pre-filled as an example for
CAT02, CAT03, CAT04 but NOT for CAT01 -- so we only auto-write "NEW" for
those three.
"""

from copy import copy
from openpyxl.styles import PatternFill

RULE_TARIFF_START_ROW = 5   # "Rule & Tariff" table, columns A/B/C

# Any row where a resolver set entry["ai_used"] = True gets this fill
# applied across the whole row -- per-row granularity (not per-cell) per
# project decision: simpler, less code to touch, good enough for a loader
# to know "this row needs review" without pinpointing the exact field.
AI_USED_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

CAT01_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y",
    "FareType": "K", "PassengerType": "AA", "AccountCode": "Z",
    "MinAge": "AB", "MaxAge": "AC", "IDRequired": "AD", "InboundOutbound": "AE",
}
CAT01_START_ROW = 13

CAT02_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "NotPermitted": "Z", "TimeOfDayFirst": "AA", "TimeOfDayLast": "AB", "DayRange": "AC",
    "Mon": "AD", "Tue": "AE", "Wed": "AF", "Thu": "AG", "Fri": "AH", "Sat": "AI", "Sun": "AJ",
    "DepartureFromFareOrigin": "AK", "InboundOutbound": "AL", "DI": "AM",
}
CAT02_START_ROW = 21

CAT03_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "SeasonType": "L",  # NOTE: this is the shared "Season Type" column in the MARKETS
                         # block -- for CAT03 rows it's filled from the CAT03-Seasonality
                         # tab's SEASONALITY column (confirmed by cross-checking the
                         # template layout against the DataMapping)
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "FirstDate": "Z", "LastDate": "AA", "SeasonalPromotional": "AB",
    "AppliesFor": "AC", "InboundOutbound": "AD", "DI": "AE",
}
CAT03_START_ROW = 29

CAT04_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "Travel": "Z", "Flight1": "AA", "OI": "AY",
    # Carrier1/Table1/Relation/Flight2/3/Carrier2/3 and the whole Geographic
    # Application block (AJ-AX) are intentionally NOT mapped -- no
    # DataMapping exists for them yet (see project notes).
}
CAT04_START_ROW = 37

CARRIER1_COLS = {
    "CAT4_ID": "V", "OI": "W", "No": "X",
    "OperatingCarrier": "Z", "FlightNumber1": "AA",
    # MarketingCarrier (Y) and FlightNumber2 (AB) not mapped -- no DataMapping yet
}
CARRIER1_START_ROW = 45

CAT05_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y",
    "ADVDuration": "AA", "ADVUnit": "AB",
    # Time(Z)/NBR(AC)/Day(AD) in this group, Confirmed Sectors(AE), the
    # whole "ADV Res" block (AF-AM), and both Ticketing blocks (AN-AW) are
    # intentionally NOT mapped -- no DataMapping exists for them yet.
}
CAT05_START_ROW = 53

CAT06_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y",
    "Duration": "AB", "Unit": "AC", "MeasuredFromTSI": "AE", "ReturnTravelFromTSI": "AI",
    # Number/Day (DAY OF WEEK, Z-AA), Time Of Day (AD), and Type/Loc1/Loc2
    # within both MEASURED FROM and RETURN TRAVEL FROM are not mapped.
}
CAT06_START_ROW = 63

CAT07_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y",
    "ReturnTravel": "Z", "Duration": "AC", "Unit": "AD", "MeasuredFromTSI": "AF", "ReturnTravelFromTSI": "AJ",
    # Number/Day (DAY OF WEEK, AA-AB), Time Of Day (AE), and Type/Loc1/Loc2
    # within both MEASURED FROM and RETURN TRAVEL FROM are not mapped.
}
CAT07_START_ROW = 71

CAT08_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "MaxPermitted": "Z", "EitherOutOrIn": "AA", "MinRequired": "AB",
    "Outbound": "AC", "Inbound": "AD",
    "Charge1NbrStops": "AE", "Charge1Amt1": "AF", "Charge1Cur1": "AG",
    "Charge1NoCharge": "AH", "Charge1Amt2": "AI", "Charge1Cur2": "AJ",
    "Charge2NbrStops": "AK", "Charge2Amt1": "AL", "Charge2Cur1": "AM",
    "Charge2Amt2": "AN", "Charge2Cur2": "AO",
    "ChargesApplyFor": "AP", "StopoverLOCsCarriers": "AQ", "NoteText": "AR",
}
CAT08_START_ROW = 82

CAT09_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    # No RI/Table/CAT/category-specific columns exist for CAT09 -- verified
    # directly against the template, not an oversight.
}
CAT09_START_ROW = 91

CAT10_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "OW/RT": "L", "AltGenTariff": "P", "AltGenRule": "Q",
    "SingleOpenJaw": "AI", "DoubleOpenJaw": "AK",
    "CircleTripPermitted": "AM", "EndOnEndPermitted": "AP",
    # Not APL/EFF/DISC (M-O), the three RI/Table/CAT/I-O/DI groups (S-AG),
    # Origin/Destination (AJ), and the OW-Fare-Allowed columns (AL/AO) have
    # no DataMapping yet -- intentionally not written.
}
CAT10_START_ROW = 99

# Qualifying Tables 106/107 live far below the main CAT10 block (rows
# 131-152 in the original template, not immediately adjacent like Carrier
# Table No.1 was for CAT04) -- written separately in write_to_template.
TABLE106_COLS = {"PermittedNotPermitted": "Q", "Carrier1": "R"}
TABLE106_START_ROW = 134
TABLE107_COLS = {"Tariff": "R", "Rule": "S"}
TABLE107_START_ROW = 140

CAT11_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "LOC1": "F", "Zone1": "G", "LOC2": "H", "Zone2": "I", "FareClassFamily": "J",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "DayRange": "Z", "Date1": "AA", "Date2": "AB",
}
CAT11_START_ROW = 161

CAT12_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "SurchargeType": "Z",
    # LOC1/Zone1/LOC2/Zone2/FareClassFamily (Markets block) and the whole
    # Charge Information / Applies To blocks (AA-AW) are not written yet
    # -- no mapping exists.
}
CAT12_START_ROW = 169

CAT13_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    # No RI/Table/CAT/category-specific columns exist for CAT13 -- verified
    # directly against the template, same as CAT09.
}
CAT13_START_ROW = 178

CAT14_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "OnAfterCommence": "Z", "OnBeforeCommence": "AA",
}
CAT14_START_ROW = 187

CAT15_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "SellAndTicket": "Z", "OwningOALGDS": "AA",
    "Location1Exclude": "AC", "Location1Type": "AD", "Location1Value": "AE",
    "Location2Exclude": "AG", "Location2Type": "AH", "Location2Value": "AI",
    "Location3Exclude": "AK", "Location3Type": "AL", "Location3Value": "AM",
    "TicketingMAIL": "AO", "TicketingPTA": "AP", "TicketingPTAEqualsTicket": "AQ",
    "TicketingElectronic": "AR", "TicketingSelfTicket": "AS",
    "TicketingSATOCATO": "AT", "TicketingAutoTicketing": "AU",
    "ReservationMustBeOnAfter": "AV", "ReservationMustBeOnBefore": "AW",
    "TicketMustBeIssuedOnAfter": "AX", "TicketMustBeIssuedOnBefore": "AY",
}
CAT15_START_ROW = 195

CAT16_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y",
    # Table NOT confirmed as "NEW" for this category (no example in the
    # template, unlike every other category) -- deliberately not defaulted.
}
CAT16_START_ROW = 204

CAT17_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "TravelViaHIPNotPermitted": "Z", "StopoversConnections": "AA",
}
CAT17_START_ROW = 213

CAT18_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    # has_mapping=False -- no category-specific fields ever populated,
    # but Table="NEW" is still confirmed as an example in the template.
}
CAT18_START_ROW = 222

CAT19_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    "CAT_NUM": "Y", "Table": "X",
    "PSGRType": "Z", "MinAge": "AA", "MaxAge": "AB",
    "Percent": "AG", "TicketDesignator": "AH",
    "AccompaniedTravel": "AL", "SameCMPT": "AM", "AccompanyingMinAge": "AO",
    "NoDiscount": "AF",
}
CAT19_START_ROW = 231

CAT20_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N", "Table": "X",
}
CAT20_START_ROW = 240

CAT21_COLS = dict(CAT20_COLS)
CAT21_START_ROW = 249

CAT22_COLS = dict(CAT20_COLS)
CAT22_START_ROW = 258

# CAT23 is the one outlier: columns shifted one position left vs every
# other category (LOC1 is missing entirely from this block -- Zone1 sits
# first), confirmed directly against the template.
CAT23_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "O", "AltGenRule": "P", "OW/RT": "M",
    # No Table column confirmed for this category.
}
CAT23_START_ROW = 267

CAT26_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    # No RI/Table/CAT confirmed for this category -- block stops at
    # column V (Sequence). Assumed same as CAT20 before, WRONG -- fixed
    # after direct re-verification.
}
CAT26_START_ROW = 276

CAT27_COLS = dict(CAT26_COLS)
CAT27_START_ROW = 285

CAT28_COLS = dict(CAT26_COLS)
CAT28_START_ROW = 294

CAT29_COLS = dict(CAT26_COLS)
CAT29_START_ROW = 303

CAT31_COLS = dict(CAT20_COLS)
CAT31_START_ROW = 312

CAT33_COLS = {
    "NO": "A", "PRICEBOOK NAME": "B", "SAME AS BASE REFERENCE FARE ?": "C", "RULE": "D", "TARIFF": "E",
    "AltGenTariff": "P", "AltGenRule": "Q", "OW/RT": "N",
    # No RI/Table/CAT confirmed for this category (same as CAT09/13/18 pattern).
}
CAT33_START_ROW = 321

COLS_BY_CATEGORY = {
    "CAT01": CAT01_COLS,
    "CAT02": CAT02_COLS,
    "CAT03": CAT03_COLS,
    "CAT04": CAT04_COLS,
    "CAT05": CAT05_COLS,
    "CAT06": CAT06_COLS,
    "CAT07": CAT07_COLS,
    "CAT08": CAT08_COLS,
    "CAT09": CAT09_COLS,
    "CAT10": CAT10_COLS,
    "CAT11": CAT11_COLS,
    "CAT12": CAT12_COLS,
    "CAT13": CAT13_COLS,
    "CAT14": CAT14_COLS,
    "CAT15": CAT15_COLS,
    "CAT16": CAT16_COLS,
    "CAT17": CAT17_COLS,
    "CAT18": CAT18_COLS,
    "CAT19": CAT19_COLS,
    "CAT20": CAT20_COLS,
    "CAT21": CAT21_COLS,
    "CAT22": CAT22_COLS,
    "CAT23": CAT23_COLS,
    "CAT26": CAT26_COLS,
    "CAT27": CAT27_COLS,
    "CAT28": CAT28_COLS,
    "CAT29": CAT29_COLS,
    "CAT31": CAT31_COLS,
    "CAT33": CAT33_COLS,
}


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
    """
    style_cache = [copy(ws.cell(row=start_row, column=c)._style) for c in range(1, max_col + 1)]

    for i, row in enumerate(rows):
        excel_row = start_row + i
        for c in range(1, max_col + 1):
            ws.cell(row=excel_row, column=c)._style = style_cache[c - 1]
            if row.get("ai_used"):
                ws.cell(row=excel_row, column=c).fill = AI_USED_FILL

        ws[f"{no_col}{excel_row}"] = i + 1
        for field, col_letter in columns.items():
            if field == "NO":
                continue
            value = row.get(field)
            if value is not None:
                ws[f"{col_letter}{excel_row}"] = value


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
