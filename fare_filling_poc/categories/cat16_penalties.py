import os
import re
from categories.base import CategoryResolver, needs_ai_fallback, AI_SPECS_DIR
from ai_engine import extract_with_ai
from common_fields import _lookup_owrt_type23, _owrt_type23_applies


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
        used for CAT31, which shares this exact pattern. The "Free
        rebooking for RBDs..." part has no structured field to go into
        (output_fields=[], same as Type 1) -- kept as a flag, not
        discarded silently.
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No CAT16 row found in Fare Rules (Type {sheet_type})")])

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

            # AI fallback: text has content, isn't a no-op phrase, but
            # regex found neither an explicit column value nor an
            # embedded "IPRG rule <code>" phrase -- try AI once before
            # leaving AltGenRule blank (output_fields is empty for this
            # category, so this only targets AltGenRule specifically,
            # not the whole entry).
            if needs_ai_fallback(override_text, alt_gen_rule):
                ai_result = extract_with_ai(override_text, {"rule_id": rule_id, "category": self.category},
                                             os.path.join(AI_SPECS_DIR, self.ai_spec_file), ["AltGenRule"])
                alt_gen_rule = ai_result.get("AltGenRule")
                entry["ai_used"] = ai_result.get("ai_used", False)
                # AltGenRule isn't a key of `entry` here (it flows through
                # common_override below instead) -- mark it directly so
                # template_writer.py can still highlight its specific cell.
                if ai_result.get("AltGenRule") is not None:
                    entry.setdefault("ai_fields", set()).add("AltGenRule")
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
