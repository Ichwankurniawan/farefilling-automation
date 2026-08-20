import re
from categories.base import CategoryResolver


class Cat08Resolver(CategoryResolver):
    category = "CAT08"
    has_mapping = True
    ai_spec_file = "cat08_spec.yaml"
    output_fields = [
        "MaxPermitted", "EitherOutOrIn", "MinRequired", "Outbound", "Inbound",
        "Charge1NbrStops", "Charge1Amt1", "Charge1Cur1", "Charge1NoCharge", "Charge1Amt2", "Charge1Cur2",
        "Charge2NbrStops", "Charge2Amt1", "Charge2Cur1", "Charge2Amt2", "Charge2Cur2",
        "ChargesApplyFor", "StopoverLOCsCarriers", "NoteText",
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("08")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT08 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()

        # Branch 1: "REFER TO <tab>" -- deterministic lookup, same pattern
        # as CAT03/04/05.
        match = re.search(r'REFER TO\s+"?([^"]+)"?', condition_text, re.IGNORECASE)
        if match:
            target_tab = match.group(1).strip()
            rows = pricebook_data.get_tab(target_tab) or pricebook_data.get_tab("CAT08-Stopovers")
            found = next((r for r in rows if r.get("RULE") == rule_id), None)
            if found is None:
                return self._bundle(rule_id, sheet_type, "REFER_YES",
                                     [self._flagged_entry(f"No matching row in {target_tab}")])
            entry = {f: found.get(f) for f in self.output_fields}
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            return self._bundle(rule_id, sheet_type, "REFER_YES", [entry])

        # Branch 2: free text (e.g. "UNLIMITED FREE STOPOVERS PERMITTED...")
        # -- genuinely the AI-fallback case per the project's architecture
        # decision: this kind of keyword-dependent interpretation (Max
        # Permitted keyword, No Charge inferred from "FREE", Charges Apply
        # For default) belongs in ai_specs/cat08_spec.yaml as guidance,
        # not hardcoded regex -- real-world phrasing varies too much for
        # a fixed pattern to stay reliable.
        entry = self._ai_extract_entry(condition_text, rule_id)
        return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])
