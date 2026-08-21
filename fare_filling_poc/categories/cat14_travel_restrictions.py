import re
from categories.base import CategoryResolver, needs_ai_fallback
from common_fields import _lookup_owrt_type23, _owrt_type23_applies


class Cat14Resolver(CategoryResolver):
    category = "CAT14"
    has_mapping = True
    ai_spec_file = "cat14_spec.yaml"
    # "On/After (Commence)" and "On/Before (Commence)" are documented AUTO,
    # but explicitly deferred for Type 1: "No request to code these yet".
    # Type 2/3 DOES have a confirmed extraction rule now (see
    # _resolve_type2_3 below) -- kept as real output fields (always None
    # for Type 1) rather than omitted, so the column exists and is easy
    # to wire up later without touching the writer config again.
    # Everything else in this category (Return Travel, Return By Date/
    # Time, Commence TSI/Type/LOC1/LOC2) has no mapping instructions at all.
    output_fields = ["OnAfterCommence", "OnBeforeCommence"]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("14")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT14 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()

        if self._is_none_condition(condition_text):
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        # CAT14's sample condition is "REFER TO TAB 'Filing Instructions'"
        # -- not a market-level tab, so there's no row-expansion here (see
        # CLAUDE.md). Deferred fields stay None regardless of branch.
        entry = self._blank_entry()
        entry["flag_reason"] = "OnAfterCommence/OnBeforeCommence deferred by design -- not coded for Type 1 yet"
        return self._bundle(rule_id, sheet_type, "DEFERRED_FIELDS", [entry])

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        Confirmed rule (Type 2): row "Travel Dates" » Same as Base
        Reference Fare? -- IF 'No' AND override text contains 'ON/AFTER'
        THEN extract the date; same for 'ON/BEFORE'. IF 'Yes' THEN blank.
        Type 3 reads the same phrases from a differently-named column
        ("Same as Base Rule OR Amend Base Rule as indicated") -- same
        extraction logic either way once we have the override text.
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No CAT14 row found in Fare Rules (Type {sheet_type})")])

        entry = {f: None for f in self.output_fields}
        same_as_base = (row.get("same_as_base") or "").strip().upper()

        if same_as_base in ("YES", "NA", ""):
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            branch = "SAME_AS_BASE"
        else:
            override_text = row.get("override_text") or ""
            after_match = re.search(r'ON/AFTER\s+(\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4})', override_text,
                                     re.IGNORECASE)
            before_match = re.search(r'ON/BEFORE\s+(\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4})', override_text,
                                      re.IGNORECASE)
            entry["OnAfterCommence"] = after_match.group(1) if after_match else None
            entry["OnBeforeCommence"] = before_match.group(1) if before_match else None
            branch = "TYPE2_3_EXTRACTED"

            # AI fallback: text exists and isn't a no-op phrase, but the
            # regex found NEITHER date -- try AI before giving up (e.g.
            # "COMMENCEMENT PERMITTED FROM <date> THROUGH <date>" phrasing,
            # confirmed real case that doesn't match "ON/AFTER"/"ON/BEFORE").
            if needs_ai_fallback(override_text, entry["OnAfterCommence"]) and \
               needs_ai_fallback(override_text, entry["OnBeforeCommence"]):
                ai_result = self._ai_extract_entry(override_text, rule_id)
                self._copy_ai_fields(entry, ai_result, ["OnAfterCommence", "OnBeforeCommence"])
                entry["confidence"] = ai_result["confidence"]
                entry["flag_reason"] = ai_result["flag_reason"]
                entry["ai_used"] = ai_result.get("ai_used", False)
                branch = "AI_EXTRACTED"
            else:
                entry["confidence"] = "HIGH" if (after_match or before_match) else "LOW"
                entry["flag_reason"] = None if (after_match or before_match) else \
                    f"Same as Base = 'No' but no ON/AFTER or ON/BEFORE phrase found: {override_text!r}"

        bundle = self._bundle(rule_id, sheet_type, branch, [entry])
        alt_gen_rule = row.get("alt_gen_rule")
        bundle["common_override"] = {
            "SAME AS BASE REFERENCE FARE ?": row.get("same_as_base"),
            "AltGenTariff": "IPRG" if alt_gen_rule else None,
            "AltGenRule": alt_gen_rule,
            "OW/RT": _lookup_owrt_type23(pricebook_data) if _owrt_type23_applies(self.category, sheet_type) else None,
        }
        return bundle
