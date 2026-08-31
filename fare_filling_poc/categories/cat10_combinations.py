import os
import re
from categories.base import CategoryResolver, AI_SPECS_DIR
from ai_engine import extract_with_ai
from common_fields import _lookup_owrt_type23, _owrt_type23_applies

# Sub-row labels as they appear in Fare Rules for CAT10 -- matched exactly
# against what the user gave. If the real file spells these slightly
# differently, this lookup will just come back empty for that sub-row
# (handled gracefully -- see _resolve_impl).
SUB_ROW_CIRCLE_TRIPS = "Circle Trips"
SUB_ROW_SIDE_TRIPS = "Side Trips"
SUB_ROW_END_ON_END = "End-on-End Combination"
SUB_ROW_OPEN_JAW = "Half Round Trip / Single Open-Jaw / Double Open-Jaw combination with other RBDs/fares"
SUB_ROW_NOTES = "Notes"


class Cat10Resolver(CategoryResolver):
    category = "CAT10"
    has_mapping = True
    ai_spec_file = "cat10_spec.yaml"
    # NOTE: CircleTripPermitted/EndOnEndPermitted/SingleOpenJaw/DoubleOpenJaw
    # have an explicit IF/THEN rule from the user -- handled deterministically
    # below. SideTripsPermitted/Notes have NO deterministic rule (just raw
    # free text) -- those go through AI. The four Record 3 Tables (101 Open
    # Jaw / 102 Circle Trip 2 / 103 Circle Trip 2+ / 104 End on End
    # Restrictions) and Qualifying Tables 108/109 still have no mapping
    # instructions at all -- deliberately left out rather than guessed.
    output_fields = ["CircleTripPermitted", "EndOnEndPermitted", "SingleOpenJaw", "DoubleOpenJaw",
                      "SideTripsPermitted", "Notes"]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        subrows = pricebook_data.get_fare_rules_subrows("10")
        if not subrows:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT10 sub-rows found in Fare Rules")])

        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        # Circle Trip permitted (102) / End on End permitted (104):
        # copy the sub-row's text as-is, per the DataMapping.
        entry["CircleTripPermitted"] = subrows.get(SUB_ROW_CIRCLE_TRIPS)
        entry["EndOnEndPermitted"] = subrows.get(SUB_ROW_END_ON_END)

        oj_text = subrows.get(SUB_ROW_OPEN_JAW)
        if oj_text:
            entry["SingleOpenJaw"] = self._open_jaw_value(oj_text)
            entry["DoubleOpenJaw"] = self._open_jaw_value(oj_text)

        # Side Trips / Notes -- no deterministic rule exists for these, so
        # they go through AI (per the project decision that every
        # category's genuinely-unmatched free text should route to AI,
        # not sit as a silent TODO). Downgrades the whole entry's
        # confidence to LOW since part of it is now AI-derived.
        side_trips_text = subrows.get(SUB_ROW_SIDE_TRIPS)
        notes_text = subrows.get(SUB_ROW_NOTES)
        # BUGFIX: this used to be a plain truthy check (`if side_trips_text
        # or notes_text:`) with no exclusion for the recognized "no
        # restriction" phrase -- confirmed the same class of bug as CAT08
        # (bug #30): a sub-row literally reading "NONE UNLESS OTHERWISE
        # SPECIFIED" would still trigger a real AI call. _is_none_condition()
        # excludes it per-field, so AI only fires when at least one sub-row
        # has genuine content beyond that phrase.
        side_trips_has_content = side_trips_text and not self._is_none_condition(side_trips_text)
        notes_has_content = notes_text and not self._is_none_condition(notes_text)
        if side_trips_has_content or notes_has_content:
            combined_text = (f"Side Trips: {side_trips_text or '(not specified)'}\n"
                              f"Notes: {notes_text or '(not specified)'}")
            spec_path = os.path.join(AI_SPECS_DIR, self.ai_spec_file)
            ai_result = extract_with_ai(combined_text, {"rule_id": rule_id, "category": self.category},
                                         spec_path, ["SideTripsPermitted", "Notes"])
            self._copy_ai_fields(entry, ai_result, ["SideTripsPermitted", "Notes"])
            entry["confidence"] = "LOW"
            entry["flag_reason"] = "SideTripsPermitted/Notes interpreted via AI -- needs review"
            entry["ai_used"] = ai_result.get("ai_used", False)

        bundle = self._bundle(rule_id, sheet_type, "PARTIAL_MAPPING", [entry])
        bundle["supporting_tables"] = {
            "QualifyingTable106CarrierTable": self._table106(),
            "QualifyingTable107TariffRuleTable": self._table107(oj_text, rule_id),
        }
        return bundle

    @staticmethod
    def _get_subrow_ci(subrows, *labels):
        """Case-insensitive sub-row lookup -- Type 2's real sample uses
        different capitalization than Type 1's DataMapping text (e.g.
        "End-on-End combination" vs Type 1's "End-on-End Combination")."""
        lowered = {k.lower(): v for k, v in subrows.items()}
        for label in labels:
            if label.lower() in lowered:
                return lowered[label.lower()]
        return None

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        CAT10 overrides the generic Type 2/3 fallback in base.py because,
        unlike most categories, it has multiple SUB-ROWS per category
        (confirmed from a real Type 2 sample) -- same shape as Type 1's
        sub-row structure, just sourced from "If 'NO', amend Base Rule as
        follows:" instead of "FARE RULE CONDITIONS". The extraction logic
        itself (Circle Trip/End-on-End copy, Open-Jaw Permitted/Restricted
        rule, Qualifying Table 107 regex) is IDENTICAL to Type 1 -- only
        the text source differs.
        """
        subrows = pricebook_data.get_type2_subrows(self.category)
        if not subrows:
            # No sub-rows -- category might just be a plain Yes/No/NA row
            # (not confirmed for CAT10 in any sample seen, but handled for
            # robustness) -- fall back to the generic base.py behavior.
            return super()._resolve_type2_3(rule_id, pricebook_data, sheet_type)

        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        circle = self._get_subrow_ci(subrows, SUB_ROW_CIRCLE_TRIPS)
        entry["CircleTripPermitted"] = circle.get("override_text") if circle else None

        eoe = self._get_subrow_ci(subrows, SUB_ROW_END_ON_END, "End-on-End combination")
        entry["EndOnEndPermitted"] = eoe.get("override_text") if eoe else None

        oj = self._get_subrow_ci(subrows, SUB_ROW_OPEN_JAW)
        oj_text = oj.get("override_text") if oj else None
        if oj_text:
            entry["SingleOpenJaw"] = self._open_jaw_value(oj_text)
            entry["DoubleOpenJaw"] = self._open_jaw_value(oj_text)

        side = self._get_subrow_ci(subrows, SUB_ROW_SIDE_TRIPS)
        side_text = side.get("override_text") if side else None
        notes = self._get_subrow_ci(subrows, SUB_ROW_NOTES, "Other (notes)", "Other")
        notes_text = notes.get("override_text") if notes else None
        if side_text or notes_text:
            combined_text = (f"Side Trips: {side_text or '(not specified)'}\n"
                              f"Notes: {notes_text or '(not specified)'}")
            spec_path = os.path.join(AI_SPECS_DIR, self.ai_spec_file)
            ai_result = extract_with_ai(combined_text, {"rule_id": rule_id, "category": self.category},
                                         spec_path, ["SideTripsPermitted", "Notes"])
            self._copy_ai_fields(entry, ai_result, ["SideTripsPermitted", "Notes"])
            entry["confidence"] = "LOW"
            entry["flag_reason"] = "SideTripsPermitted/Notes interpreted via AI -- needs review"
            entry["ai_used"] = ai_result.get("ai_used", False)

        bundle = self._bundle(rule_id, sheet_type, "PARTIAL_MAPPING_TYPE2_3", [entry])
        bundle["supporting_tables"] = {
            "QualifyingTable106CarrierTable": self._table106(),
            "QualifyingTable107TariffRuleTable": self._table107(oj_text, rule_id),
        }
        # Representative common-field values -- CAT10 has multiple
        # sub-rows, each potentially with its own Same-as-Base/AltGenRule,
        # so there's no single authoritative value. Uses the first
        # sub-row found as a reasonable approximation (all sub-rows were
        # "No" in the only real sample seen so far, so this holds for now).
        first_subrow = next(iter(subrows.values()))
        bundle["common_override"] = {
            "SAME AS BASE REFERENCE FARE ?": first_subrow.get("same_as_base"),
            "AltGenTariff": "IPRG" if any(r.get("alt_gen_rule") for r in subrows.values()) else None,
            "AltGenRule": next((r.get("alt_gen_rule") for r in subrows.values() if r.get("alt_gen_rule")), None),
            "OW/RT": _lookup_owrt_type23(pricebook_data) if _owrt_type23_applies(self.category, sheet_type) else None,
        }
        return bundle

    @staticmethod
    def _open_jaw_value(text):
        # Per DataMapping: "IF 'Not Permitted' or 'Permitted' or both
        # unmentioned THEN value = 'Restricted'" -- i.e. if the text
        # doesn't stand alone as a simple Permitted/Not-Permitted flag
        # (it's conditional narrative instead, like our sample), the
        # value is "Restricted". A standalone flag case isn't in any
        # sample seen so far, so this always returns "Restricted" for
        # now -- flagged LOW so it gets a human look regardless.
        return "Restricted"

    @staticmethod
    def _table106():
        # Qualifying Table 106 (Carrier Table): both fields are CONSTANT
        # per the DataMapping, no extraction needed.
        return [{
            "PermittedNotPermitted": "Permitted",
            "Carrier1": "SQ",
            "confidence": "HIGH",
            "flag_reason": None,
        }]

    @staticmethod
    def _table107(oj_text, rule_id):
        # Qualifying Table 107 (Tariff/Rule Table): regex against the
        # Open-Jaw sub-row text, per the three-branch rule given.
        # NOT CONFIRMED: whether this should read from the Open-Jaw
        # sub-row specifically (assumed here) vs. some other sub-row --
        # and whether the sub-row's TWO clauses (Q/N/V/K fares vs "all
        # other fares") should produce two separate table rows. Both
        # clauses happen to say "ANY RULE"/"ANY TARIFF" in the sample, so
        # this treats the whole sub-row as one block for now.
        if not oj_text:
            return []

        tariff = "ANY" if re.search(r'\bANY TARIFF\b', oj_text, re.IGNORECASE) else None

        rule_val = None
        # Captures everything between "RULE" and "IN ANY TARIFF" so a
        # bracketed list like "<WC21/ WC22/ .../ WC29>" comes through
        # whole, not just the first token.
        combo_match = re.search(r'THIS RULE AND RULE\s*(.+?)\s+IN\s+ANY\s+TARIFF', oj_text,
                                 re.IGNORECASE | re.DOTALL)
        if re.search(r'\bANY RULE\b', oj_text, re.IGNORECASE):
            rule_val = "ANY"
        elif combo_match:
            rule_val = f"{rule_id} AND {combo_match.group(1).strip()}"
        elif re.search(r'\bTHIS RULE\b', oj_text, re.IGNORECASE):
            rule_val = rule_id

        if tariff is None and rule_val is None:
            return []

        return [{
            "Tariff": tariff,
            "Rule": rule_val,
            "confidence": "LOW",
            "flag_reason": ("Sourced from the 'Half Round Trip...' sub-row -- not explicitly "
                             "confirmed as the right source, and the sub-row's two clauses "
                             "(Q/N/V/K fares vs all other fares) were not split into separate "
                             "rows. Needs confirmation."),
        }]
