from categories.base import CategoryResolver


class Cat16Resolver(CategoryResolver):
    category = "CAT16"
    has_mapping = True
    ai_spec_file = "cat16_spec.yaml"
    # SKELETON ONLY -- per user: "hanya ada sedikit mapping". Only
    # AltGenRule (common field, automatic) and OW/RT are confirmed. The 15
    # category-specific columns (Before/After Departure, NONREF/No RES
    # Change, Charge Type x3, Charge Amount x7, Charge Applies To x2) have
    # NO mapping instructions. Two sub-rows exist with real content
    # ("Voluntary Change/Refund/No show" -> a pointer to an unseen
    # "FARE FAMILY FEE CONDITIONS" source; "Notes" -> free text with a
    # service fee amount) but neither has a confirmed extraction rule --
    # not guessed here.
    output_fields = []

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        subrows = pricebook_data.get_fare_rules_subrows("16")
        if not subrows:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT16 sub-rows found in Fare Rules")])

        entry = self._flagged_entry(
            "CAT16 has almost no confirmed field mapping yet -- 'Voluntary Change/Refund/No show' "
            "(pointer to an unseen Fare Family Fee source) and 'Notes' (free-text service fee) both "
            "have no extraction rule defined. Only common fields (incl. AltGenRule, OW/RT) are populated."
        )
        return self._bundle(rule_id, sheet_type, "PARTIAL_MAPPING", [entry])

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
