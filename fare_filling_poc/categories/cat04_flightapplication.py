import re
from categories.base import CategoryResolver
from common_fields import _lookup_owrt

AIRPORT_CODE_RE = re.compile(r'^[A-Z]{3}$')
# "All" is treated as a LOC value (not a Zone) per user confirmation --
# even though it isn't a real 3-letter airport code, the real template
# expects it under LOC1/LOC2 directly, not Zone1/Zone2.
LOC_VALUE_RE = re.compile(r'^(?:[A-Z]{3}|ALL)$', re.IGNORECASE)
FLIGHT_CODE_RE = re.compile(r'([A-Z]{2}\d{3})')
OPERATED_BY_RE = re.compile(r'OPERATED BY\s+([A-Z]{2,3})', re.IGNORECASE)
DIRECTIONS = [("OUTBOUND SECTORS AND FLIGHTS", "O"), ("INBOUND SECTORS AND FLIGHTS", "I")]


class Cat04Resolver(CategoryResolver):
    category = "CAT04"
    has_mapping = True
    ai_spec_file = "cat04_spec.yaml"
    output_fields = ["LOC1", "Zone1", "LOC2", "Zone2", "FareClassFamily", "Travel", "OI", "Flight1", "Table"]

    # Fields still fully unmapped per the DataMapping we have -- left out
    # of output_fields entirely rather than guessed:
    #   Carrier1/2/3, Relation, Flight2/3, and the whole Geographic
    #   Application block (15 columns). See project notes.

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        row = pricebook_data.get_fare_rules_row("04")
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry("No CAT04 row found in Fare Rules")])

        condition_text = (row.get("FARE RULE CONDITIONS") or "").strip()
        if condition_text.upper() == "NONE UNLESS OTHERWISE SPECIFIED":
            bundle = self._bundle(rule_id, sheet_type, "NONE_UNLESS_SPECIFIED", [self._blank_entry()])
            bundle["supporting_tables"] = {"CarrierTableNo1": []}
            return bundle

        match = re.search(r'REFER TO\s+"?([^"]+)"?', condition_text, re.IGNORECASE)
        if not match:
            # Free text that's neither "REFER TO..." nor "NONE UNLESS
            # OTHERWISE SPECIFIED" -- genuine AI-fallback case.
            entry = self._ai_extract_entry(condition_text, rule_id)
            bundle = self._bundle(rule_id, sheet_type, "AI_EXTRACTED", [entry])
            bundle["supporting_tables"] = {"CarrierTableNo1": []}
            return bundle

        target_tab = match.group(1).strip()
        rows = pricebook_data.get_tab(target_tab) or pricebook_data.get_tab("CAT04-FlightApplication")

        entries = []
        carrier_rows = []
        carrier_seq = 0

        for market_row in rows:
            # Most real files split OUTBOUND/INBOUND SECTORS AND FLIGHTS
            # into separate columns (DIRECTIONS below). One confirmed
            # real shape instead has a single "FLIGHT APPLICATION" text
            # covering both directions in one IF/THEN blob, no split at
            # all -- xlsm_loader signals this with a "FLIGHT APPLICATION
            # TEXT" key instead. Apply that same text to both O and I
            # rows since there's nothing in the source to tell them apart.
            if "FLIGHT APPLICATION TEXT" in market_row:
                row_directions = [("FLIGHT APPLICATION TEXT", "O"), ("FLIGHT APPLICATION TEXT", "I")]
            else:
                row_directions = DIRECTIONS

            for text_col, oi in row_directions:
                text = (market_row.get(text_col) or "").strip()
                if not text:
                    continue  # this direction has no data -- skip, no row generated

                general_statement, exceptions_block = self._split_general_and_exceptions(text)

                entry = {f: None for f in self.output_fields}
                entry["confidence"] = "HIGH"
                entry["flag_reason"] = None

                origin = market_row.get("ORIGIN", "")
                dest = market_row.get("DESTINATION", "")
                if LOC_VALUE_RE.match(origin or ""):
                    entry["LOC1"] = origin
                else:
                    entry["Zone1"] = origin
                if LOC_VALUE_RE.match(dest or ""):
                    entry["LOC2"] = dest
                else:
                    entry["Zone2"] = dest

                entry["FareClassFamily"] = self._get_fare_class_family(market_row)
                entry["Travel"] = general_statement
                entry["OI"] = oi
                # Flight1 is confirmed to always be "SQ" -- previously
                # hardcoded to "GA", which turned out to just be the
                # carrier used in this project's own synthetic test file
                # (Garuda Indonesia), not the real constant.
                entry["Flight1"] = "SQ"
                entry["Table"] = "NEW"          # CONSTANT
                # Overrides common_fields.py's generic OW/RT fallback --
                # CAT04 has its own Fare Class per row, so match the
                # "Output" tab specifically instead of relying on every
                # row agreeing on one code project-wide.
                entry["OW/RT"] = _lookup_owrt(pricebook_data, entry["FareClassFamily"])

                # local sequence within this bundle -- the pipeline combiner
                # is responsible for translating this into the real global
                # "No" column once all categories' rows are merged into the
                # final output, and updating CAT4_ID to match.
                local_seq = len(entries)
                entries.append(entry)

                operating_carrier = self._extract_operating_carrier(general_statement)
                for flight_code in self._extract_exception_flight_codes(exceptions_block):
                    carrier_seq += 1
                    carrier_rows.append({
                        "CAT4_ID_local_ref": local_seq,   # see note above
                        "OI": oi,
                        "No": carrier_seq,
                        "OperatingCarrier": operating_carrier,
                        "FlightNumber1": flight_code,
                    })

        if not entries:
            entries = [self._flagged_entry("No OUTBOUND/INBOUND SECTORS AND FLIGHTS data found")]

        bundle = self._bundle(rule_id, sheet_type, "REFER_YES", entries)
        bundle["supporting_tables"] = {"CarrierTableNo1": carrier_rows}
        return bundle

    @staticmethod
    def _get_fare_class_family(market_row):
        """
        Looks up by keyword rather than an exact header string -- real
        files have been seen with different whitespace/newline placement
        around "FARE BASIS /" vs "FARE CLASS FAMILY" (e.g. no leading
        space, embedded newline mid-phrase), and an exact-match lookup
        silently returned None on one of them, dropping the field
        entirely instead of just being resilient to formatting noise.
        """
        for key, value in market_row.items():
            if not key:
                continue
            key_upper = str(key).upper()
            if "FARE BASIS" in key_upper and "FARE CLASS FAMILY" in key_upper:
                return value
        return None

    @staticmethod
    def _split_general_and_exceptions(text):
        parts = re.split(r'Except\s*:', text, maxsplit=1, flags=re.IGNORECASE)
        general = parts[0].strip()
        exceptions = parts[1].strip() if len(parts) > 1 else ""
        return general, exceptions

    @staticmethod
    def _extract_operating_carrier(general_statement):
        m = OPERATED_BY_RE.search(general_statement)
        return m.group(1) if m else None

    @staticmethod
    def _extract_exception_flight_codes(exceptions_block):
        if not exceptions_block:
            return []
        return FLIGHT_CODE_RE.findall(exceptions_block)
