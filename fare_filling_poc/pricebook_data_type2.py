"""
PricebookData for Type 2/3 pricebooks -- structurally very different from
Type 1's PricebookData (see pricebook_data.py): instead of a flat
FARE RULE CONDITIONS per category, most categories have exactly ONE row
with a "Same as Base Reference Fare (Yes/No/NA)?" flag -- but some (e.g.
CAT10, confirmed) have MULTIPLE sub-rows per category, same shape as
Type 1's sub-row categories (CAT10/15/16 etc there). So every category
is stored as a LIST of rows here, even when there's normally just one.
"""


class PricebookDataType2:
    def __init__(self, rule_id, category_rows, owrt_rows=None):
        """
        category_rows: dict of {"CAT 01": [{...}], "CAT 10": [{...}, {...}, ...]}
        each row dict: {
            "description": "Eligibility" (or sub-row label like "Circle Trips" for multi-row cats),
            "same_as_base": "Yes" / "No" / "NA",
            "override_text": "..." or None,
            "alt_gen_rule": "1HK1" or None,
        }

        owrt_rows: raw rows from the real per-fare-class "Edifact/NDC/
        Faresheet" data sheet (NOT the "Fare Rules"/"...POO" sheet) --
        carries the "RT/OW" column used by common_fields.py's
        _lookup_owrt_type23(). Empty list if that sheet wasn't found (e.g.
        a file shape we haven't seen yet) rather than None, so callers
        don't need a None-check.
        """
        self.rule_id = rule_id
        self._categories = category_rows
        self.owrt_rows = owrt_rows or []

    def get_type2_row(self, category):
        """First (or only) row for this category. category e.g. 'CAT01' or '01'."""
        rows = self._categories.get(_normalize_category_key(category))
        return rows[0] if rows else None

    def get_type2_subrows(self, category):
        """
        {sub_row_label: row_dict} for categories with multiple rows (like
        CAT10's Circle Trips/Side Trips/etc). Empty dict if the category
        has 0 or 1 row (use get_type2_row() for the simple case).
        """
        rows = self._categories.get(_normalize_category_key(category), [])
        if len(rows) <= 1:
            return {}
        return {r["description"]: r for r in rows if r.get("description")}


def _normalize_category_key(category):
    digits = "".join(c for c in category if c.isdigit())
    return f"CAT {digits.zfill(2)}" if digits else category
