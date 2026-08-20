import re

OWRT_CODE_MAP = {1: "OW", 2: "RT", 3: "OW/RT"}  # confirmed: 1=OW only, 2=RT, 3=OW/RT (both)

# Type 2/3's OW/RT value domain is TEXT, not Type 1's numeric 1/2/3 codes --
# confirmed via Final Data Mapping: the real per-fare-class data sheet's
# "RT/OW" column holds "RT/OW" (both directions permitted) or "OW"
# (one-way only). Only "RT/OW" has been seen in real samples so far.
OWRT_TEXT_MAP = {"RT/OW": "OW/RT", "OW": "OW"}

# Which categories DataMapping actually documents an OW/RT source for under
# Type 2/3, and which sheet type(s) -- confirmed by checking EVERY category's
# OW/RT row in data_mapping_final.json directly, not assumed. Every other
# category explicitly says "No request to code these yet" for OW/RT under
# Type 2/3 (or has no OW/RT row in DataMapping at all) -- that's a real
# business decision to leave the field blank there, not a gap this code
# should paper over just because the lookup mechanism CAN technically
# resolve a value project-wide. (Corrected after initially wiring this into
# EVERY category's generic Type 2/3 path -- wrong: it populated OW/RT on
# categories DataMapping never asked for it on, e.g. CAT16/CAT31.)
OWRT_TYPE23_CATEGORIES = {
    "CAT10": {2, 3},
    "CAT11": {2, 3},
    "CAT14": {2, 3},
    "CAT15": {2, 3},
    "CAT19": {2, 3},
    "CAT03": {3},  # Type 2 explicitly "No request to code these yet" -- Type 3 only
}


def _owrt_type23_applies(category, sheet_type):
    return sheet_type in OWRT_TYPE23_CATEGORIES.get(category, set())


def _lookup_owrt_type23(pricebook_data):
    """
    Type 2/3 analog of _lookup_owrt() below -- same conservative "only
    resolve if every row agrees" rule, but reading a COMPLETELY different
    source: `pricebook_data.owrt_rows` (the real per-fare-class "Edifact/
    NDC/Faresheet" data sheet, NOT the "Output" tab, which doesn't exist
    on Type 2/3 files at all -- see xlsm_loader.py's _read_owrt_rows()).

    No per-category Fare Class context exists for the generic Type 2/3
    branch (unlike Type 1's CAT03/04/05/06/07/11, which each have their
    own per-row Fare Class to narrow the match), so this only resolves
    project-wide -- exactly like Type 1's own fallback when no Fare Class
    is passed in.
    """
    owrt_rows = getattr(pricebook_data, "owrt_rows", None)
    if not owrt_rows:
        return None
    texts = {str(r.get("RT/OW")).strip().upper() for r in owrt_rows if r.get("RT/OW") is not None}
    if len(texts) != 1:
        return None  # no data, or rows disagree -- don't guess
    return OWRT_TEXT_MAP.get(texts.pop())


def _lookup_owrt(pricebook_data, fare_class_text=None):
    """
    OW/RT's real source is the "Output" tab, which has ONE ROW PER FARE
    CLASS (not one per RULE) -- confirmed on a real file where the same
    RULE had both OW/RT=2 and OW/RT=3 across different Fare Class rows.
    So a single "common field" value only makes sense when either (a) we
    have a specific Fare Class to match against (pass fare_class_text --
    e.g. CAT04 already resolves one per row), or (b) every row happens to
    agree on the same code anyway.

    fare_class_text may combine multiple codes ("VT6HKR / KT6HKR", as
    CAT04's FareClassFamily does) -- matches against any of them. Returns
    None (not a guess) if there's no tab, no match, or matched rows
    disagree on the code.
    """
    if not hasattr(pricebook_data, "get_tab"):
        return None
    output_rows = pricebook_data.get_tab("Output")
    if not output_rows:
        return None

    rows_to_check = output_rows
    if fare_class_text and fare_class_text.strip().upper() not in ("ALL", "ALL FARE CLASSES"):
        # CAT04's FareClassFamily can be a PREFIX ("KV6-", trailing dash)
        # rather than a full code -- the Output tab always has full codes
        # ("KV6HKR", "KV6HKO", ...). Match by prefix, not exact equality,
        # or a prefix-style value never matches anything at all.
        wanted = {c.strip().upper().rstrip("-") for c in re.split(r'\s*/\s*', fare_class_text) if c.strip()}
        wanted = {w for w in wanted if w}
        matched = [r for r in output_rows
                   if any(str(r.get("Fare Class", "")).strip().upper().startswith(w) for w in wanted)]
        if matched:
            rows_to_check = matched

    codes = {r.get("OW/RT") for r in rows_to_check if r.get("OW/RT") is not None}
    if len(codes) != 1:
        return None  # no data, or matched rows disagree -- don't guess
    return OWRT_CODE_MAP.get(int(codes.pop()))


def extract_common_fields(anchor_row, pricebook_data, category=None):
    """
    anchor_row: dict with RULE, TARIFF, PRICEBOOK_NAME, sheet_type
    category: e.g. "CAT08" -- the category currently being resolved. Needed
              because AltGenRule's IPRG code is PER-CATEGORY (CAT01-04 all
              happen to share "AB60" in our sample data, which is what let
              a bug slip through here: without `category`, this used to
              grab the first IPRG value found across ANY category's Fare
              Rules row -- wrong for CAT08, which has its own "HK60".
    Returns a dict of the fields shared by every category's output row.

    AltGenTariff / AltGenRule logic: IF General Rule == "N/A" (or absent)
    AND there's no instruction to refer to another sheet, THEN pull the
    4-char code from the Fare Rules "IPRG" column. Simplified here since
    our sample data always satisfies that condition.
    """
    common = {
        "PRICEBOOK NAME": anchor_row["PRICEBOOK_NAME"],
        "SAME AS BASE REFERENCE FARE ?": "NA",
        "RULE": anchor_row["RULE"],
        "TARIFF": anchor_row["TARIFF"],
        # TARIFF / Footnote 1 / Footnote 2 are MANUAL (loader-entered at
        # upload time) -- already present on the anchor row for TARIFF;
        # footnotes are not modeled in this POC.
        "AltGenTariff": "IPRG",
        "AltGenRule": _extract_iprg_code(pricebook_data, category),
        # Fallback for categories with no fare-class context of their own
        # -- only resolves to something if every "Output" row agrees on
        # one code. Categories that DO have their own fare class (CAT04)
        # override this per-row with a specific match -- see
        # cat04_flightapplication.py.
        "OW/RT": _lookup_owrt(pricebook_data),
    }
    return common


def _get_iprg_value(row):
    """
    Look up the Fare Rules row's IPRG column by value, not by exact key
    match -- confirmed on a real file where the header reads
    "IPRG\\n[Check with FMU]" instead of a bare "IPRG" (same column,
    an annotation appended to the header text). `row.get("IPRG")` alone
    silently returns None on that file and drops every AltGenRule.
    """
    for key, value in row.items():
        if key and str(key).strip().upper().startswith("IPRG"):
            return value
    return None


def _extract_iprg_code(pricebook_data, category=None):
    # PricebookDataType2 (Type 2/3) doesn't have get_fare_rules_row -- its
    # AltGenRule comes from a different mechanism entirely (the "For
    # HO/TCS: Alt Gen Rule IPRG" / "IPRG Rule" column, applied via
    # base.py's _resolve_type2_3 -> bundle["common_override"], which
    # overrides whatever this function returns anyway). Return None
    # rather than crashing on the missing method.
    if not hasattr(pricebook_data, "get_fare_rules_row"):
        return None

    if category:
        cat_num = category.replace("CAT", "")
        row = pricebook_data.get_fare_rules_row(cat_num)
        if row:
            iprg = _get_iprg_value(row)
            if iprg:
                parts = iprg.split()
                if len(parts) == 2:
                    return parts[1]
        return None

    # No category given -- BUGGY fallback kept only so any old caller that
    # forgets to pass `category` fails loudly-ish (wrong value) rather than
    # crashing; every real call site should always pass category now.
    for rows in pricebook_data._fare_rules.values():
        for row in rows:
            iprg = _get_iprg_value(row)
            if iprg:
                parts = iprg.split()
                if len(parts) == 2:
                    return parts[1]
    return None
