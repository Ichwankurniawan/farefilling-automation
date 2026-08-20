import os
import re
from categories.base import CategoryResolver, needs_ai_fallback, AI_SPECS_DIR
from ai_engine import extract_with_ai
from common_fields import _lookup_owrt_type23, _owrt_type23_applies


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
        separate IPRG column (confirmed blank in the real sample).
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No CAT31 row found in Fare Rules (Type {sheet_type})")])

        same_as_base = (row.get("same_as_base") or "").strip().upper()
        override_text = row.get("override_text") or ""

        if same_as_base in ("YES", "NA", "NOT APPLICABLE", ""):
            entry = self._blank_entry()
            branch = "SAME_AS_BASE"
            alt_gen_rule = row.get("alt_gen_rule")
        else:
            iprg_match = re.search(r'IPRG\s+RULE\s+(\S+)', override_text, re.IGNORECASE)
            alt_gen_rule = iprg_match.group(1) if iprg_match else row.get("alt_gen_rule")
            entry = self._flagged_entry(
                f"No structured field for the rebooking-conditions text -- raw text: {override_text!r}")
            branch = "TYPE2_3_EXTRACTED"

            if needs_ai_fallback(override_text, alt_gen_rule):
                ai_result = extract_with_ai(override_text, {"rule_id": rule_id, "category": self.category},
                                             os.path.join(AI_SPECS_DIR, self.ai_spec_file), ["AltGenRule"])
                alt_gen_rule = ai_result.get("AltGenRule")
                entry["ai_used"] = ai_result.get("ai_used", False)
                entry["flag_reason"] = (entry["flag_reason"] or "") + \
                    " | AltGenRule attempted via AI (no regex match found)"
                branch = "AI_EXTRACTED"

        bundle = self._bundle(rule_id, sheet_type, branch, [entry])
        bundle["common_override"] = {
            "SAME AS BASE REFERENCE FARE ?": row.get("same_as_base"),
            "AltGenTariff": "IPRG" if alt_gen_rule else None,
            "AltGenRule": alt_gen_rule,
            "OW/RT": _lookup_owrt_type23(pricebook_data) if _owrt_type23_applies(self.category, sheet_type) else None,
        }
        return bundle
