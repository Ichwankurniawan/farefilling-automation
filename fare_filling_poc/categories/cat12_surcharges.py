import re
from categories.base import CategoryResolver


class Cat12Resolver(CategoryResolver):
    category = "CAT12"
    has_mapping = True
    ai_spec_file = "cat12_spec.yaml"
    # SKELETON ONLY -- per user instruction: "Surcharge Type" stays empty
    # (its CONSTANT value is ambiguous -- DataMapping just says "Comment
    # marked for deletion, ATPCO reads the code only", not an actual
    # value). The whole "CHARGE INFORMATION" block (Amount1/Currency/No
    # Charge/Percent of fare/Amount2/Currency2/Add-Subtract/Charges will
    # be Applied/Fee Applies Per) and both "APPLIES TO ..." geo blocks
    # (TSI/Type/LOC1/LOC2 x2) have NO DataMapping at all yet -- not
    # mapped, not guessed. Fill these in once the CAT12-Surcharges tab
    # sample and its field mapping are available.
    output_fields = ["SurchargeType"]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("12")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT12 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()
        normalized = condition_text.upper()

        if normalized == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        match = re.search(r'REFER TO\s+"?([^"]+)"?', condition_text, re.IGNORECASE)
        if not match:
            entry = self._ai_extract_entry(condition_text, rule_id)
            return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])

        target_tab = match.group(1).strip()
        rows = pricebook_data.get_tab(target_tab) or pricebook_data.get_tab("CAT12-Surcharges")
        if not rows:
            # Expected for now -- no CAT12-Surcharges tab sample exists
            # yet. Row still gets flagged rather than silently dropped.
            return self._bundle(rule_id, sheet_type, "REFER_YES",
                                 [self._flagged_entry(f"Referenced tab '{target_tab}' not available yet -- "
                                                       "no sample data or field mapping provided")])

        entries = [self._map_row(r) for r in rows]
        return self._bundle(rule_id, sheet_type, "REFER_YES", entries)

    def _map_row(self, r):
        # Placeholder -- once the CAT12-Surcharges tab structure is known,
        # this fills in LOC1/Zone1/LOC2/Zone2/FareClassFamily (same
        # pattern as CAT03/05/11) plus the Charge Information / Applies To
        # fields once mapped.
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "LOW"
        entry["flag_reason"] = "CAT12-Surcharges tab reader not implemented yet -- skeleton only"
        return entry
