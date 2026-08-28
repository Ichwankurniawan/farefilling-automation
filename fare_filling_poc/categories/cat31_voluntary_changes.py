from categories.base import CategoryResolver


class Cat31Resolver(CategoryResolver):
    category = "CAT31"
    ai_spec_file = "cat31_spec.yaml"  # ready but not yet used -- has_mapping stays False below
    # AltGenRule: DataMapping says "Refer to 'COMMON RECORD FIELDS' section
    # above" -- meaning the standard IPRG-based common field mechanism
    # (already handled automatically by common_fields.py for every
    # category, per-category since the CAT08 bug fix) applies here for
    # Type 1. Fare Rules sample: "31 VOLUNTARY CHANGES FARE FAMILY FEE
    # CONDITIONS IPRG 0011" -> AltGenRule="0011" via the usual mechanism.
    #
    # Category-specific columns (Changes not PERM, Number of Changes,
    # Reissue Table, Request is Made) have no mapping instructions at all
    # -- "FARE FAMILY FEE CONDITIONS" points to an unseen external source,
    # same pattern as CAT16.
    has_mapping = False
    output_fields = []

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        CONFIRMED: CAT31 has its OWN separate Fare Rules Type 2 row (not
        merged with CAT16, despite both categories' "Category Description"
        happening to read "Penalties / Rebooking" -- an earlier version of
        this file flagged that as ambiguous; resolved once real per-
        category samples showed each has its own "CAT 16"/"CAT 31" row).
        Same extraction mechanism as CAT16: AltGenRule is embedded in the
        override text ("...Please tag IPRG rule <code>"), not in the
        separate IPRG column (confirmed blank in the real sample) -- the
        actual logic lives once in base.py's
        _resolve_type2_3_embedded_iprg().
        """
        return self._resolve_type2_3_embedded_iprg(rule_id, pricebook_data, sheet_type)
