import os
import re
from categories.base import CategoryResolver, needs_ai_fallback, AI_SPECS_DIR
from ai_engine import extract_with_ai
from common_fields import _lookup_owrt_type23, _owrt_type23_applies

# PSGR Type is determined by POSITION, not by parsing the sub-row label --
# confirmed by the user: "Row 1 = CNN, Row 2 = UNN, Row 3 = INS, Row 4 = INF"
# is a fixed writing convention, not something to extract per-file.
PSGR_TYPE_BY_POSITION = ["CNN", "UNN", "INS", "INF"]

AGE_RANGE_RE = re.compile(r'(\d+)\s*-\s*(\d+)')
AGE_UNDER_RE = re.compile(r'UNDER\s+(\d+)', re.IGNORECASE)

# Splits condition text into per-booking-class clauses, e.g.
# "FOR F-/A- FARE TYPE:- ... FOR Z-/C-/.../K- FARE TYPE:- ..."
CLAUSE_SPLIT_RE = re.compile(r'FOR\s+[\w/\-]+\s*(?:FARE\s+)?TYPE\s*:-', re.IGNORECASE)
CHARGE_RE = re.compile(r'CHARGE\s+(\d+)%\s+OF\s+THE\s+FARE\.?\s*TICKET\s+DESIGNATOR\s*-\s*(\S+)', re.IGNORECASE)
ACCOMPANIED_RE = re.compile(r'MUST\s+BE\s+ACCOMPANIED.*?BY\s+ADULT\s+(\d+)', re.IGNORECASE | re.DOTALL)


class Cat19Resolver(CategoryResolver):
    category = "CAT19"
    has_mapping = True
    ai_spec_file = "cat19_spec.yaml"
    output_fields = [
        "PSGRType", "MinAge", "MaxAge",
        "Percent", "TicketDesignator",
        "AccompaniedTravel", "SameCMPT", "AccompanyingMinAge",
        "NoDiscount",
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        subrows = pricebook_data.get_fare_rules_subrows("19")
        if not subrows:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT19 sub-rows found in Fare Rules")])

        entries = []
        for i, (label, condition_text) in enumerate(subrows.items()):
            entries.append(self._map_subrow(i, label, condition_text or ""))

        return self._bundle(rule_id, sheet_type, "PARTIAL_MAPPING", entries)

    def _map_subrow(self, position, label, condition_text):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        # PSGR Type -- fixed by position, always confirmed regardless of
        # how the label text is worded.
        entry["PSGRType"] = PSGR_TYPE_BY_POSITION[position] if position < len(PSGR_TYPE_BY_POSITION) else None

        # MIN/MAX Age -- parsed from the LABEL (e.g. "2-11" or "Under 2"),
        # not from the condition text body.
        range_match = AGE_RANGE_RE.search(label)
        under_match = AGE_UNDER_RE.search(label)
        if range_match:
            entry["MinAge"] = int(range_match.group(1))
            entry["MaxAge"] = int(range_match.group(2))
        elif under_match:
            entry["MinAge"] = 0
            entry["MaxAge"] = int(under_match.group(1)) - 1

        # Percent / Ticket Designator / Accompanied info -- from the
        # condition text body. If multiple "FOR ... FARE TYPE:-" clauses
        # exist, take the LAST one (confirmed heuristic: the broader
        # catch-all clause, not the narrow premium-cabin one) and flag the
        # row LOW since this is a default choice, not a certain match.
        clauses = CLAUSE_SPLIT_RE.split(condition_text)
        clause_count_with_content = len([c for c in clauses if c.strip()])
        target_clause = clauses[-1] if clauses else condition_text

        charge_match = CHARGE_RE.search(target_clause)
        if charge_match:
            entry["Percent"] = int(charge_match.group(1))
            entry["TicketDesignator"] = charge_match.group(2).rstrip(".")

        accompanied_match = ACCOMPANIED_RE.search(target_clause)
        if accompanied_match:
            entry["AccompaniedTravel"] = "YES"
            entry["SameCMPT"] = "YES"
            entry["AccompanyingMinAge"] = int(accompanied_match.group(1))

        flags = []

        # AI fallback: the clause has real content but the CHARGE regex
        # found neither a percent nor a ticket designator -- try AI before
        # leaving these blank (e.g. phrasing that doesn't say "CHARGE X%
        # OF THE FARE. TICKET DESIGNATOR - Y" verbatim).
        if needs_ai_fallback(target_clause, entry["Percent"]) and \
           needs_ai_fallback(target_clause, entry["TicketDesignator"]):
            ai_result = extract_with_ai(target_clause, {"rule_id": self.category, "category": self.category},
                                         os.path.join(AI_SPECS_DIR, self.ai_spec_file),
                                         ["Percent", "TicketDesignator", "AccompaniedTravel",
                                          "SameCMPT", "AccompanyingMinAge"])
            self._copy_ai_fields(entry, ai_result, ["Percent", "TicketDesignator", "AccompaniedTravel",
                                                     "SameCMPT", "AccompanyingMinAge"])
            entry["ai_used"] = ai_result.get("ai_used", False)
            flags.append("Percent/TicketDesignator not found via regex -- attempted via AI")

        # No Discount -- HYPOTHESIS only (confirmed from a single example:
        # Percent == 100 -> "YES"). Not a documented rule -- always flags
        # the row when applied.
        if clause_count_with_content > 1:
            flags.append("Multiple FARE TYPE clauses in this sub-row -- used the LAST clause as the "
                          "default (broadest booking-class coverage); verify this matches the actual "
                          "booking class being filed.")
        if entry["Percent"] == 100:
            entry["NoDiscount"] = "YES"
            flags.append("NoDiscount='YES' inferred from Percent==100 -- unconfirmed heuristic from a "
                          "single example, not a documented rule.")

        if flags:
            entry["confidence"] = "LOW"
            entry["flag_reason"] = " | ".join(flags)

        return entry

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        Type 2/3's CAT19 has NO CNN/UNN/INS/INF sub-row breakdown (unlike
        Type 1) -- confirmed: reads from the category's own single row
        ("Children / Infant Discounts"), same Yes/No/NA mechanism as
        every other simple Type 2/3 category. 'No' -> the override text
        itself becomes NoDiscount verbatim (not the Percent==100 guess
        Type 1 uses -- Type 2 has an actual documented rule here).
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No CAT19 row found in Fare Rules (Type {sheet_type})")])

        entry = {f: None for f in self.output_fields}
        same_as_base = (row.get("same_as_base") or "").strip().upper()

        if same_as_base in ("YES", "NA", "NOT APPLICABLE", ""):
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            branch = "SAME_AS_BASE"
        else:
            entry["NoDiscount"] = row.get("override_text")
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            branch = "TYPE2_3_EXTRACTED"

        bundle = self._bundle(rule_id, sheet_type, branch, [entry])
        alt_gen_rule = row.get("alt_gen_rule")
        bundle["common_override"] = {
            "SAME AS BASE REFERENCE FARE ?": row.get("same_as_base"),
            "AltGenTariff": "IPRG" if alt_gen_rule else None,
            "AltGenRule": alt_gen_rule,
            "OW/RT": _lookup_owrt_type23(pricebook_data) if _owrt_type23_applies(self.category, sheet_type) else None,
        }
        return bundle

    def resolve_poo_single(self, poo_row, rule_id):
        """
        Confirmed real sample: POO value is "NO CHILD AND INFANT
        DISCOUNTS" (not "FOLLOW ..."), with its own IPRG Rule ("1HO1") --
        maps directly onto NoDiscount, same as the main-sheet mechanism,
        rather than going through blind AI extraction.
        """
        entry = {f: None for f in self.output_fields}
        entry["NoDiscount"] = poo_row.get("poo_value")
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None
        return entry
