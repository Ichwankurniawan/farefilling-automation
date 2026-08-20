from categories.base import CategoryResolver


class Cat17Resolver(CategoryResolver):
    category = "CAT17"
    has_mapping = True
    ai_spec_file = "cat17_spec.yaml"
    # No field-level mapping exists at all -- only OW/RT (common). This
    # category is the reason base.py gained NONE_PHRASES/_is_none_condition():
    # its sample condition is "UNLESS OTHERWISE SPECIFIED DOES NOT APPLY",
    # a different phrasing of "no restriction" than the exact-match every
    # earlier category used ("NONE UNLESS OTHERWISE SPECIFIED"). Without
    # recognizing both, this would have wrongly fallen through to AI.
    output_fields = ["TravelViaHIPNotPermitted", "StopoversConnections"]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("17")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT17 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()

        if self._is_none_condition(condition_text):
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        entry = self._ai_extract_entry(condition_text, rule_id)
        return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])
