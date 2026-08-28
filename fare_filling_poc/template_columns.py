"""
Column-letter and start-row mapping for every category block in the real
uploaded template (SQ_Fare_Filling_Template.xlsx, sheet
"(FINAL TEMPLATE) CAT 1-CAT 33 w"/" "). Pure data, no writing logic --
split out of template_writer.py (previously ~310 lines of constants sitting
directly above the actual write functions) so the two concerns -- "where
does each field live in the template" vs. "how do we write a value there"
-- can be read, checked against the real file, and changed independently.

Column letters below were read directly from the template with openpyxl,
not guessed -- see the header rows for each category block in the real
file. Header rows and title rows are merged cells; every data row (13+,
21+, 29+, 37+, 45+) is NOT merged, so writing cell-by-cell is safe (see
template_writer.py's _write_block()).

Confirmed from the template itself (useful new info beyond what was in
the DataMapping doc): "Table" = "NEW" is pre-filled as an example for
CAT02, CAT03, CAT04 but NOT for CAT01 -- so template_writer.py only
auto-writes "NEW" for those (and the other categories confirmed the same
way -- see each SIMPLE_CATEGORIES_PART*'s needs_table_default flag there).

This module is imported into template_writer.py via `from
template_columns import *` (see __all__ below) so every existing
CATxx_COLS / CATxx_START_ROW / COLS_BY_CATEGORY reference in that file's
writing logic, and every external `from template_writer import
COLS_BY_CATEGORY` (categories/base.py), keeps working completely
unchanged -- this split is a pure move, not a behavior or API change.
"""

RULE_TARIFF_START_ROW = 5   # "Rule & Tariff" table, columns A/B/C

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
    # Table 103 ("Circle Trip 2+ Application Tags") has its OWN "Permitted"
    # column at AN -- confirmed by reading the real template directly
    # (row 97/98: AM97="102 - Circle Trip 2...", AN97="103 - Circle Trip
    # 2+...", each with their own "Permitted" sub-header at AM98/AN98).
    # This was genuinely never wired up (not a formatting bug -- CAT10_COLS
    # simply had no entry for it). There's only ONE "Circle Trips" sub-row
    # in the source Fare Rules (no separate "2" vs "2+" condition exists),
    # so table 103 mirrors whatever table 102 (CircleTripPermitted)
    # resolved -- see the mirroring step in _write_pipeline_output_to_sheet()
    # (SIMPLE_CATEGORIES_PART1 loop) rather than a second independent
    # extraction. Confirmed against a real user-provided example where both
    # columns held the identical value.
    "CircleTrip2PlusPermitted": "AN",
    # Not APL/EFF/DISC (M-O), the three RI/Table/CAT/I-O/DI groups (S-AG),
    # Origin/Destination (AJ), and the OW-Fare-Allowed columns (AL/AO) still
    # have no DataMapping at all -- intentionally not written (no known
    # source cell, unlike table 103's Permitted column above).
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

# Explicit re-export list -- template_writer.py does `from template_columns
# import *`, and this pins exactly which names cross that boundary (every
# CATxx_COLS/CATxx_START_ROW plus the lookup tables) rather than leaking
# anything unintended. Keep this in sync when adding a new category.
__all__ = [
    "RULE_TARIFF_START_ROW",
    "CAT01_COLS", "CAT01_START_ROW",
    "CAT02_COLS", "CAT02_START_ROW",
    "CAT03_COLS", "CAT03_START_ROW",
    "CAT04_COLS", "CAT04_START_ROW",
    "CARRIER1_COLS", "CARRIER1_START_ROW",
    "CAT05_COLS", "CAT05_START_ROW",
    "CAT06_COLS", "CAT06_START_ROW",
    "CAT07_COLS", "CAT07_START_ROW",
    "CAT08_COLS", "CAT08_START_ROW",
    "CAT09_COLS", "CAT09_START_ROW",
    "CAT10_COLS", "CAT10_START_ROW",
    "TABLE106_COLS", "TABLE106_START_ROW",
    "TABLE107_COLS", "TABLE107_START_ROW",
    "CAT11_COLS", "CAT11_START_ROW",
    "CAT12_COLS", "CAT12_START_ROW",
    "CAT13_COLS", "CAT13_START_ROW",
    "CAT14_COLS", "CAT14_START_ROW",
    "CAT15_COLS", "CAT15_START_ROW",
    "CAT16_COLS", "CAT16_START_ROW",
    "CAT17_COLS", "CAT17_START_ROW",
    "CAT18_COLS", "CAT18_START_ROW",
    "CAT19_COLS", "CAT19_START_ROW",
    "CAT20_COLS", "CAT20_START_ROW",
    "CAT21_COLS", "CAT21_START_ROW",
    "CAT22_COLS", "CAT22_START_ROW",
    "CAT23_COLS", "CAT23_START_ROW",
    "CAT26_COLS", "CAT26_START_ROW",
    "CAT27_COLS", "CAT27_START_ROW",
    "CAT28_COLS", "CAT28_START_ROW",
    "CAT29_COLS", "CAT29_START_ROW",
    "CAT31_COLS", "CAT31_START_ROW",
    "CAT33_COLS", "CAT33_START_ROW",
    "COLS_BY_CATEGORY",
]
