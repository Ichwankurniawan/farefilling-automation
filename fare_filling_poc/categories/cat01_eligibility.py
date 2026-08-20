import re
from categories.base import CategoryResolver


class Cat01Resolver(CategoryResolver):
    category = "CAT01"
    has_mapping = True
    ai_spec_file = "cat01_spec.yaml"
    output_fields = [
        "FareType", "PassengerType", "AccountCode",
        "MinAge", "MaxAge", "IDRequired", "InboundOutbound",
    ]

    # Confirmed label vocabulary from the "amend Base Rule as follows" override
    # text. Only one label is verified so far -- unrecognized labels get
    # flagged rather than silently dropped.
    KNOWN_LABELS = {
        "PAX TYPE CODE": "PassengerType",
    }

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("01")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT01 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()
        refer_flag = (row.get("Need to refer to another tab?") or "").strip().upper()

        if condition_text.upper() == "NONE UNLESS OTHERWISE SPECIFIED":
            return self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])

        elif refer_flag == "YES":
            rows = pricebook_data.get_tab("Specific Cat. No.01")
            match = self._find_matching_row(rows, rule_id)
            if match is None:
                return self._bundle(rule_id, sheet_type, "REFER_YES",
                                     [self._flagged_entry("No matching row in Specific Cat. No.01")])
            entry = {f: match.get(f) for f in self.output_fields}
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            return self._bundle(rule_id, sheet_type, "REFER_YES", [entry])

        elif refer_flag == "NO":
            override_text = row.get("If 'NO', amend Base Rule as follows:", "") or ""
            entry = self._parse_override_text(override_text)
            return self._bundle(rule_id, sheet_type, "REFER_NO", [entry])

        else:
            # Free text that's neither "REFER TO..." nor an explicit YES/NO
            # flag response, and not "NONE UNLESS OTHERWISE SPECIFIED" --
            # this is the genuine AI-fallback case.
            entry = self._ai_extract_entry(condition_text, rule_id)
            return self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])

    def _find_matching_row(self, rows, rule_id):
        # Placeholder join -- real join key against "Specific Cat. No.01"
        # tab is still unconfirmed (no real example seen yet).
        for r in rows:
            if r.get("RULE") == rule_id:
                return r
        return None

    def _parse_override_text(self, text):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None

        pairs = re.split(r'[;\n]', text)
        unrecognized = []
        for pair in pairs:
            if ":" not in pair:
                continue
            label, value = pair.split(":", 1)
            label, value = label.strip().upper(), value.strip()
            if not label:
                continue
            if label in self.KNOWN_LABELS:
                entry[self.KNOWN_LABELS[label]] = value
            else:
                unrecognized.append(label)

        if unrecognized:
            entry["confidence"] = "LOW"
            entry["flag_reason"] = f"Unrecognized label(s): {', '.join(unrecognized)}"

        return entry
