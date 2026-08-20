from categories.base import CategoryResolver


class Cat09Resolver(CategoryResolver):
    category = "CAT09"
    # Verified directly against the real template: CAT09's block has no
    # extra columns at all beyond the common MARKETS fields -- not even
    # RI/Table/CAT, which every other category (01-08) has. So this
    # STILL resolves like a no-mapping category for Excel purposes: the
    # written row only ever carries common fields, matching the
    # template's own placeholder row count expectation.
    has_mapping = True   # True so _resolve_impl runs (for the AI note below),
                          # but no field here maps to an Excel column --
                          # template_writer.py's CAT09_COLS only knows common
                          # fields, so "Note" simply never gets written there.
    ai_spec_file = "cat09_spec.yaml"
    output_fields = ["Note"]  # JSON-only -- not written to Excel (no column exists)

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("09")
        if row is None:
            return self._bundle(rule_id, sheet_type, "NO_CATEGORY_MAPPING", [self._blank_entry()])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()
        if not condition_text or condition_text.upper() == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NO_CATEGORY_MAPPING", [self._blank_entry()])

        # Free text, and no deterministic rule exists for it (there's
        # nothing to pattern-match against, unlike CAT04/08/10) -- always
        # AI, purely for an audit note. Never written to Excel; only
        # visible in the JSON output.
        entry = self._ai_extract_entry(condition_text, rule_id)
        return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])
