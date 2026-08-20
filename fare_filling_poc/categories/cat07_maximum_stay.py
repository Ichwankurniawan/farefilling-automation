import re
from categories.base import CategoryResolver
from common_fields import _lookup_owrt

# "All" is treated as a LOC value (not a Zone) -- confirmed for CAT04 and
# applied consistently here since it's the same general origin/destination
# classification rule, not a CAT04-specific one.
LOC_VALUE_RE = re.compile(r'^(?:[A-Z]{3}|ALL)$', re.IGNORECASE)


class Cat07Resolver(CategoryResolver):
    category = "CAT07"
    has_mapping = True
    ai_spec_file = "cat07_spec.yaml"
    output_fields = [
        "LOC1", "Zone1", "LOC2", "Zone2", "FareClassFamily",
        "ReturnTravel", "Duration", "Unit", "MeasuredFromTSI", "ReturnTravelFromTSI",
        # Number/Day (DAY OF WEEK block) and Time Of Day, plus Type/Loc1/
        # Loc2 within MEASURED FROM and RETURN TRAVEL FROM, have no
        # documented column source yet -- left out rather than guessed.
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("07")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT07 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()

        if condition_text.upper() == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        match = re.search(r'REFER TO\s+"?([^"]+)"?', condition_text, re.IGNORECASE)
        if not match:
            entry = self._ai_extract_entry(condition_text, rule_id)
            return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])

        target_tab = match.group(1).strip()
        rows = pricebook_data.get_tab(target_tab) or pricebook_data.get_tab("CAT050607")
        if not rows:
            return self._bundle(rule_id, sheet_type, "REFER_YES",
                                 [self._flagged_entry(f"Referenced tab '{target_tab}' has no rows")])

        entries = [self._map_row(r, pricebook_data) for r in rows]
        return self._bundle(rule_id, sheet_type, "REFER_YES", entries)

    def _map_row(self, r, pricebook_data):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        origin, dest = r.get("ORIGIN", ""), r.get("DESTINATION", "")
        if LOC_VALUE_RE.match(origin or ""):
            entry["LOC1"] = origin
        else:
            entry["Zone1"] = origin
        if LOC_VALUE_RE.match(dest or ""):
            entry["LOC2"] = dest
        else:
            entry["Zone2"] = dest

        entry["FareClassFamily"] = self._lookup(r, "FARE BASIS", "FARE CLASS FAMILY")
        entry["ReturnTravel"] = "Commence"        # CONSTANT
        # NOTE: user's DataMapping text literally said Duration/Unit come
        # from the "MIN STAY" column -- almost certainly a copy-paste
        # error since MIN STAY belongs to CAT06. Using "MAX STAY" here as
        # the logical choice for Maximum Stay, flagged LOW pending the
        # user's explicit confirmation either way.
        max_stay = r.get("MAX STAY")
        max_stay_unit = r.get("MAX STAY UNIT")
        entry["Duration"] = max_stay
        entry["Unit"] = max_stay_unit
        if max_stay is not None:
            entry["confidence"] = "LOW"
            entry["flag_reason"] = ("Duration/Unit sourced from 'MAX STAY' column -- user's DataMapping text said "
                                     "'MIN STAY', likely a copy-paste error (MIN STAY belongs to CAT06). "
                                     "Needs explicit confirmation.")
        entry["MeasuredFromTSI"] = "01"           # CONSTANT
        entry["ReturnTravelFromTSI"] = "05"       # CONSTANT

        # Overrides common_fields.py's generic OW/RT fallback -- CAT07 has
        # its own Fare Class per row (same reasoning as CAT03/CAT04), so
        # match the "Output" tab specifically instead of relying on every
        # row project-wide agreeing on one code.
        entry["OW/RT"] = _lookup_owrt(pricebook_data, entry["FareClassFamily"])
        return entry

    @staticmethod
    def _lookup(row, *keywords):
        """
        Looks up a column by keyword rather than an exact header string --
        the real header is "FARE BASIS /\\nFARE CLASS FAMILY" (an embedded
        newline, not a plain space), which an exact-match lookup never
        matches -- confirmed to silently drop FareClassFamily (and, by
        extension, OW/RT, which needs it) on every real file seen so far.
        """
        for key, value in row.items():
            if not key:
                continue
            key_upper = str(key).upper()
            if all(kw in key_upper for kw in keywords):
                return value
        return None
