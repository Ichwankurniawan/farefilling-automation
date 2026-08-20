"""
Wraps one pricebook's worth of tab data (Fare Rules + category tabs)
and provides the lookup helpers every category resolver needs.

This is a lightweight in-memory stand-in for "read the XLSM file" --
in production this would be backed by openpyxl reading the actual
uploaded file. For now it's populated from plain dict/list structures
so we can test the resolver logic without needing a real file.
"""


class PricebookData:
    def __init__(self, rule_id, fare_rules_rows, tabs=None, filing_instructions=None):
        """
        rule_id: the RULE this pricebook file belongs to (one file = one RULE)
        fare_rules_rows: list of dicts, one per category, e.g.
            {"CAT": "01", "FARE RULE CONDITIONS": "...",
             "Need to refer to another tab?": "YES" or "NO" or None,
             "If 'NO', amend Base Rule as follows:": "..."}
        tabs: dict of tab_name -> list of row dicts, e.g.
            {"CAT03-Seasonality": [...], "CAT04-FlightApplication": [...]}
        filing_instructions: dict of {field_header: value} from the
            "Filing Instructions" tab, e.g. {"Sales From/To": ("16-Jan-2026", "28-Jan-2026")}
            -- this tab is key-value shaped (Field Header / Field Values
            columns), not row-based like the others, so it gets its own
            storage instead of going through `tabs`.
        """
        self.rule_id = rule_id
        self._fare_rules = {}
        for row in fare_rules_rows:
            self._fare_rules.setdefault(row["CAT"], []).append(row)
        self._tabs = tabs or {}
        self._filing_instructions = filing_instructions or {}

    def get_fare_rules_row(self, category):
        """Returns the FIRST Fare Rules row for this category, or None.
        Use get_fare_rules_rows() for categories that can have more than
        one condition line (e.g. CAT03/CAT04 have a second, unnumbered
        fallback line -- hypothesized to be for sheet Type != 1)."""
        rows = self._fare_rules.get(category)
        return rows[0] if rows else None

    def get_fare_rules_rows(self, category):
        """Returns ALL Fare Rules rows for this category (list, possibly empty)."""
        return self._fare_rules.get(category, [])

    def get_fare_rules_subrows(self, category):
        """
        For categories like CAT10 whose Fare Rules entry isn't one flat
        FARE RULE CONDITIONS text, but several labeled sub-conditions
        (e.g. "Circle Trips", "Side Trips", "End-on-End Combination") --
        returns {sub_row_label: condition_text} for every row that has a
        "SUB_ROW" key. Rows without one are ignored (they're the plain
        single-condition kind every other category so far has used).
        """
        rows = self._fare_rules.get(category, [])
        return {r["SUB_ROW"]: r.get("FARE RULE CONDITIONS") for r in rows if r.get("SUB_ROW")}

    def get_tab(self, tab_name):
        """Returns list of row dicts for a named tab, e.g. 'CAT03-Seasonality'"""
        return self._tabs.get(tab_name, [])

    def get_filing_instruction(self, field_header):
        """Returns the value (or tuple of values, e.g. From/To pairs) for
        a Filing Instructions field, e.g. get_filing_instruction("Sales From/To")."""
        return self._filing_instructions.get(field_header)
