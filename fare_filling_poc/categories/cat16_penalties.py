from categories.base import CategoryResolver

# Separate from `ai_spec_file` (cat16_spec.yaml) on purpose -- that file
# belongs to _resolve_type2_3_embedded_iprg() (inherited from base.py),
# which extracts a completely different thing (AltGenRule embedded in
# Type 2/3 override text) from completely different input. Reusing the
# same yaml for this Type 1 Notes extraction would silently give the
# Type 2/3 call the wrong instruction/schema -- see _ai_extract_entry()'s
# spec_file parameter docstring in base.py.
NOTES_AI_SPEC_FILE = "cat16_notes_spec.yaml"

SUB_ROW_NOTES = "Notes"
# Deliberately NOT read for extraction -- confirmed on every real sample
# seen so far (HKF1, HKF2) to be a bare pointer to an unseen external
# "FARE FAMILY FEE CONDITIONS" document ("FARE FAMILY FEE CONDITIONS -
# CAT16", verbatim, identical on both files), not a real condition.
# Kept as a named constant only so its absence from _resolve_impl below
# is a deliberate, documented choice, not an oversight.
SUB_ROW_VOLUNTARY_CHANGE = "Voluntary Change/Refund/No show"


class Cat16Resolver(CategoryResolver):
    category = "CAT16"
    has_mapping = True
    ai_spec_file = "cat16_spec.yaml"
    # Confirmed against real files (HKF1/HKF2, identical on both): only
    # the "Notes" sub-row has real, extractable content -- a single flat
    # per-ticket service fee description. Of the 34 real category-
    # specific columns in the template (Z-BD), only these 7 have any
    # grounding in that real text -- the rest (Before/After Departure,
    # Charge Type VOL/INVOL/Cancel, all 6 Waivers fields, Override Date,
    # etc.) are never mentioned in any real sample seen so far and are
    # deliberately left unmapped rather than guessed, same principle as
    # CAT05's unmapped ADV Res columns.
    output_fields = [
        "ChargeAmt1", "ChargeCur1", "AppliesPer",
        "ChargeAppliesToReissue", "ChargeAppliesToRevalidation", "ChargeAppliesToRefund",
        "NoteText",
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        subrows = pricebook_data.get_fare_rules_subrows("16")
        if not subrows:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT16 sub-rows found in Fare Rules")])

        # Only "Notes" is ever read here -- see SUB_ROW_VOLUNTARY_CHANGE's
        # comment above for why the other sub-row is deliberately excluded.
        # _is_none_condition() guard matches the fix applied to CAT08/10/15
        # (bug #30 and its follow-ups) -- a "Notes" sub-row that happens to
        # be empty or the standard no-restriction phrase must not trigger
        # a real AI call.
        notes_text = subrows.get(SUB_ROW_NOTES)
        if not notes_text or self._is_none_condition(notes_text):
            return self._bundle(rule_id, sheet_type, "NO_EXTRACTABLE_CONTENT", [self._blank_entry()])

        entry = self._ai_extract_entry(notes_text, rule_id, spec_file=NOTES_AI_SPEC_FILE)
        return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        Confirmed real sample (Type 2): "Free rebooking for RBDs W/H/M/R/
        P/L/U\nPlease tag IPRG rule 1AG7" -- the separate "For HO/TCS: Alt
        Gen Rule IPRG" column is BLANK here; the code is embedded in the
        override text itself ("tag IPRG rule <code>"). Same mechanism
        used for CAT31, which shares this exact pattern -- the actual
        logic lives once in base.py's _resolve_type2_3_embedded_iprg().
        The "Free rebooking for RBDs..." part has no structured field to
        go into (output_fields=[], same as Type 1) -- kept as a flag, not
        discarded silently.
        """
        return self._resolve_type2_3_embedded_iprg(rule_id, pricebook_data, sheet_type)
