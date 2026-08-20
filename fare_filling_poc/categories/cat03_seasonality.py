import re
from categories.base import CategoryResolver
from common_fields import _lookup_owrt

# "All" is treated as a LOC value (not a Zone) -- confirmed for CAT04 and
# applied consistently here since it's the same general origin/destination
# classification rule, not a CAT04-specific one.
LOC_VALUE_RE = re.compile(r'^(?:[A-Z]{3}|ALL)$', re.IGNORECASE)


class Cat03Resolver(CategoryResolver):
    category = "CAT03"
    has_mapping = True
    ai_spec_file = "cat03_spec.yaml"
    output_fields = [
        "LOC1", "Zone1", "LOC2", "Zone2", "FareClassFamily",
        "FirstDate", "LastDate", "SeasonType", "SeasonalPromotional",
        "AppliesFor", "InboundOutbound", "DI",
    ]

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        # NOTE: CAT03 has no "Need to refer to another tab?" flag column --
        # the branch is determined by pattern-matching the condition text
        # itself. There are also TWO condition lines in Fare Rules for this
        # category (REFER TO ... / NONE UNLESS OTHERWISE SPECIFIED) --
        # hypothesized to map to sheet Type 1 vs other, unconfirmed.
        # For now (Type 1 only implemented), we use the first row.
        row = pricebook_data.get_fare_rules_row("03")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT03 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()
        normalized = condition_text.upper()

        if normalized == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        match = re.search(r'REFER TO\s+"?([^"]+)"?', condition_text, re.IGNORECASE)
        if not match:
            # Free text that's neither "REFER TO..." nor "NONE UNLESS
            # OTHERWISE SPECIFIED" -- genuine AI-fallback case.
            entry = self._ai_extract_entry(condition_text, rule_id)
            return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])

        target_tab = match.group(1).strip()
        rows = pricebook_data.get_tab(target_tab) or pricebook_data.get_tab("CAT03-Seasonality")
        if not rows:
            return self._bundle(rule_id, sheet_type, "REFER_YES",
                                 [self._flagged_entry(f"Referenced tab '{target_tab}' has no rows")])

        entries = [self._map_row(r, pricebook_data) for r in rows]
        return self._bundle(rule_id, sheet_type, "REFER_YES", entries)

    def _map_row(self, r, pricebook_data):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        origin, dest = r.get("ORIGIN", ""), r.get("DESTINATION", "")
        if LOC_VALUE_RE.match(origin or ""):
            entry["LOC1"] = origin
        else:
            entry["Zone1"] = origin
        if LOC_VALUE_RE.match(dest or ""):
            entry["LOC2"] = dest
        else:
            entry["Zone2"] = dest

        entry["FareClassFamily"] = self._lookup(r, "FARE BASIS", "FARE CLASS FAMILY")
        entry["FirstDate"] = self._lookup(r, "PERIOD START")
        entry["LastDate"] = self._lookup(r, "PERIOD END")
        entry["SeasonType"] = self._lookup(r, "SEASONALITY")
        # SeasonalPromotional (Title row) sourcing still unconfirmed with
        # a real example -- left None, not flagged LOW here since the
        # field being empty isn't itself an error yet.

        # Overrides common_fields.py's generic OW/RT fallback -- CAT03 has
        # its own Fare Class per row (same reasoning as CAT04), so match
        # the "Output" tab specifically instead of relying on every row
        # project-wide agreeing on one code.
        entry["OW/RT"] = _lookup_owrt(pricebook_data, entry["FareClassFamily"])
        return entry

    @staticmethod
    def _lookup(row, *keywords):
        """
        Looks up a column by keyword rather than an exact header string --
        confirmed necessary on a real file where "FARE BASIS /
        FARE CLASS FAMILY" is actually "FARE BASIS /\\nFARE CLASS FAMILY"
        (an embedded newline instead of a space) and "PERIOD Start"/
        "PERIOD End" are actually "PERIOD Start (DD-MMM-YY)"/"PERIOD End
        (DD-MMM-YY)" -- exact-match lookups silently returned None on both,
        dropping FareClassFamily/FirstDate/LastDate entirely.
        """
        for key, value in row.items():
            if not key:
                continue
            key_upper = str(key).upper()
            if all(kw in key_upper for kw in keywords):
                return value
        return None
