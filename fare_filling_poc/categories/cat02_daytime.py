from categories.base import CategoryResolver

# Real template columns AD-AJ are literally labeled "M","T","W","T","F","S","S"
# (single letters, with T and S each repeated) -- ambiguous as AI prompt
# labels on their own, so we override with full day names when building
# the AI field-label context (see _resolve_impl below).
DAY_LABEL_OVERRIDE = {
    "Mon": "Monday (M)", "Tue": "Tuesday (T)", "Wed": "Wednesday (W)", "Thu": "Thursday (T)",
    "Fri": "Friday (F)", "Sat": "Saturday (S)", "Sun": "Sunday (S)",
}


class Cat02Resolver(CategoryResolver):
    category = "CAT02"
    has_mapping = True
    ai_spec_file = "cat02_spec.yaml"
    # BUGFIX: this used to have a single "DayOfWeek" field, but the real
    # template has 7 SEPARATE columns (AD-AJ, one per weekday) -- template_
    # writer.py's CAT02_COLS already correctly maps "Mon".."Sun" to those
    # columns, but this resolver never produced those keys, so the columns
    # were always blank regardless of what any extraction logic produced.
    # Also removed "OWRT" (dead field -- OW/RT is a common field handled by
    # common_fields.py via the "OW/RT" key with a slash; "OWRT" without a
    # slash never matched anything in COLS, so it never got written either).
    output_fields = [
        "NotPermitted", "TimeOfDayFirst", "TimeOfDayLast", "DayRange",
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
        "DepartureFromFareOrigin", "InboundOutbound", "DI",
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("02")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT02 row found in Fare Rules")])

        refer_flag = (row.get("Need to refer to another tab?") or "").strip().upper()

        if refer_flag == "YES":
            rows = pricebook_data.get_tab("Specific Cat. No.02")
            match = next((r for r in rows if r.get("RULE") == rule_id), None)
            if match is None:
                return self._bundle(rule_id, sheet_type, "REFER_YES",
                                     [self._flagged_entry("No matching row in Specific Cat. No.02")])
            entry = {f: match.get(f) for f in self.output_fields}
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            return self._bundle(rule_id, sheet_type, "REFER_YES", [entry])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()

        if condition_text.upper() == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        # refer_flag == "NO", or free text that isn't the exact NONE phrase --
        # CAT02 has no documented override-text field (unlike CAT01), so any
        # free text reaching here is a genuine AI-fallback case.
        entry = self._ai_extract_entry(condition_text, rule_id, label_override=DAY_LABEL_OVERRIDE)
        return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])
