import os
import re
from categories.base import CategoryResolver, AI_SPECS_DIR
from ai_engine import extract_with_ai
from common_fields import _lookup_owrt_type23, _owrt_type23_applies

SUB_ROW_TICKETING_MODE = "Ticketing Mode"

AI_TARGET_FIELDS = [
    "Location1Type", "Location1Value", "Location1Exclude",
    "Location2Type", "Location2Value", "Location2Exclude",
    "Location3Type", "Location3Value", "Location3Exclude",
    "TicketingElectronic", "TicketingMAIL", "TicketingPTA",
    "TicketingPTAEqualsTicket", "TicketingSelfTicket",
    "TicketingSATOCATO", "TicketingAutoTicketing",
]
# Included ONLY in the Type 2/3 AI call (see _resolve_type2_3) as a
# fallback target when the ON/AFTER regex fails -- Type 1's AI call
# (Location/Ticketing only) doesn't need this since Type 1 sources the
# date deterministically from Filing Instructions, not free text.
TYPE2_3_AI_TARGET_FIELDS = AI_TARGET_FIELDS + ["TicketMustBeIssuedOnAfter"]


class Cat15Resolver(CategoryResolver):
    category = "CAT15"
    has_mapping = True
    ai_spec_file = "cat15_spec.yaml"
    output_fields = AI_TARGET_FIELDS + [
        "ReservationMustBeOnAfter", "ReservationMustBeOnBefore",
        "TicketMustBeIssuedOnAfter", "TicketMustBeIssuedOnBefore",
        "SellAndTicket", "OwningOALGDS",  # confirmed unmapped -- source unknown
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("15")
        subrows = pricebook_data.get_fare_rules_subrows("15")
        main_condition = (row.get("FARE RULE CONDITIONS") or "").strip() if row else ""

        if not main_condition and not subrows:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT15 data found in Fare Rules")])

        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        # TICKET MUST BE ISSUED -- confirmed by the user to come from
        # Filing Instructions "Sales From/To". RESERVATION MUST BE stays
        # empty -- an earlier version of this code wrongly populated both
        # groups from the same source; corrected.
        sales_from_to = pricebook_data.get_filing_instruction("Sales From/To")
        if sales_from_to:
            date_from, date_to = sales_from_to
            entry["TicketMustBeIssuedOnAfter"] = date_from
            entry["TicketMustBeIssuedOnBefore"] = date_to

        # Locations + ticketing mode -- combine main condition text and the
        # Ticketing Mode sub-row, extract via AI (per project decision:
        # this needs real interpretation, not simple keyword regex).
        ticketing_mode_text = subrows.get(SUB_ROW_TICKETING_MODE)
        if main_condition or ticketing_mode_text:
            combined_text = (f"Main condition: {main_condition or '(none)'}\n"
                              f"Ticketing Mode: {ticketing_mode_text or '(none)'}")
            spec_path = os.path.join(AI_SPECS_DIR, self.ai_spec_file)
            ai_result = extract_with_ai(combined_text, {"rule_id": rule_id, "category": self.category},
                                         spec_path, AI_TARGET_FIELDS)
            self._copy_ai_fields(entry, ai_result, AI_TARGET_FIELDS)
            entry["confidence"] = "LOW"
            entry["flag_reason"] = "Locations/Ticketing mode interpreted via AI -- needs review"
            entry["ai_used"] = ai_result.get("ai_used", False)

        return self._bundle(rule_id, sheet_type, "PARTIAL_MAPPING", [entry])

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        Confirmed real sample (Type 2): the override text mixes several
        things in one block -- "FOR SALES ON/AFTER <date>" (maps to
        TicketMustBeIssuedOnAfter, same field Type 1 uses for the
        equivalent "Sales From/To" concept), plus ticket-stock/ticketing-
        mode/notes text that goes through the same AI extraction as
        Type 1 (reusing cat15_spec.yaml -- the instruction already covers
        this shape).
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No CAT15 row found in Fare Rules (Type {sheet_type})")])

        entry = {f: None for f in self.output_fields}
        same_as_base = (row.get("same_as_base") or "").strip().upper()

        if same_as_base in ("YES", "NA", "NOT APPLICABLE", ""):
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            branch = "SAME_AS_BASE"
        else:
            override_text = row.get("override_text") or ""
            # Broadened: Type 2's sample said "FOR SALES ON/AFTER <date>",
            # Type 3's real sample says "TICKETS MUST BE ISSUED ON/AFTER
            # <date>" instead -- match any "ON/AFTER <date>" regardless of
            # the preceding phrase, same principle as CAT14's regex.
            sales_after_match = re.search(r'ON/AFTER\s+(\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4})',
                                           override_text, re.IGNORECASE)
            entry["TicketMustBeIssuedOnAfter"] = sales_after_match.group(1) if sales_after_match else None

            ai_result = extract_with_ai(override_text, {"rule_id": rule_id, "category": self.category},
                                         os.path.join(AI_SPECS_DIR, self.ai_spec_file), TYPE2_3_AI_TARGET_FIELDS)
            self._copy_ai_fields(entry, ai_result, AI_TARGET_FIELDS)
            # Only use the AI's date guess as a FALLBACK -- if the regex
            # already found a date, trust that (it's a precise pattern
            # match); AI only fills in when the regex came back empty.
            # _copy_ai_fields already respects that (entry[f] or ai's
            # value), it just also now tracks it for cell highlighting.
            self._copy_ai_fields(entry, ai_result, ["TicketMustBeIssuedOnAfter"])
            entry["confidence"] = "LOW"
            entry["flag_reason"] = "Ticketing mode/other details interpreted via AI -- needs review"
            entry["ai_used"] = ai_result.get("ai_used", False)
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
        Real sample: POO value is "FOLLOW REQUESTING STATION CAT15. SALES
        DATES PER ABOVE" -- caught by the generic "FOLLOW " prefix check
        in pipeline.py already, so this hook isn't currently exercised
        for CAT15. Left as the default (None) intentionally.
        """
        return None
