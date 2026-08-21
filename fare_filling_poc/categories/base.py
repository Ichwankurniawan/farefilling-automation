"""
Base class every category resolver inherits from.

Handles the two things that are the same across ALL categories:
  1. If the category has no field-level DataMapping at all (like CAT18),
     skip straight to NO_CATEGORY_MAPPING -- no extraction attempted.
  2. Small shared helpers for building blank / flagged entries, so
     each category file doesn't repeat this boilerplate.

sheet_type is threaded through resolve() but not used for branching here
directly -- individual resolvers use it to decide whether GAP-sourced
fields apply (only for sheet_type == 1, per the temporary design).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai_engine import extract_with_ai
from template_schema import get_field_labels
from common_fields import _lookup_owrt_type23, _owrt_type23_applies

AI_SPECS_DIR = os.path.join(os.path.dirname(__file__), "..", "ai_specs")

# Different categories phrase "no restriction" slightly differently --
# discovered when CAT17 used "UNLESS OTHERWISE SPECIFIED DOES NOT APPLY"
# instead of the "NONE UNLESS OTHERWISE SPECIFIED" exact-match every
# earlier category used. Both mean the same thing (no restriction), so
# both must be recognized by the deterministic branch -- otherwise a
# category like CAT17 would wrongly fall through to AI.
NONE_PHRASES = {
    "NONE UNLESS OTHERWISE SPECIFIED",
    "UNLESS OTHERWISE SPECIFIED DOES NOT APPLY",
}

# Path to the real template -- used as the source of truth for field
# labels shown to the AI. Falls back gracefully (no labels, just internal
# key names) if this path doesn't exist in a given environment.
TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "template", "SQ Fare Filling Template.xlsx"
)


def needs_ai_fallback(text, extracted_value):
    """
    True when: (a) there's actual text, (b) it's not one of the known
    no-op phrases (NONE_PHRASES, or a "FOLLOW ..." copy-through phrase),
    and (c) the deterministic regex/logic failed to extract anything
    (extracted_value is None). Used by categories with a regex that can
    legitimately fail on real-world phrasing variance (CAT14/15/16/19/31)
    to decide whether to try AI as a second attempt, rather than silently
    leaving the field blank.
    """
    text = (text or "").strip()
    if not text:
        return False  # genuinely empty -- not a failure, nothing to extract
    upper = text.upper()
    if upper in NONE_PHRASES or upper.startswith("FOLLOW"):
        return False  # a recognized no-op phrase, not a failure case
    return extracted_value is None


class CategoryResolver:
    category = None          # e.g. "CAT01" -- set by subclass
    has_mapping = True       # False for categories like CAT18 (no field mapping at all)
    output_fields = []       # list of field names this category produces, set by subclass
    ai_spec_file = None      # e.g. "cat01_spec.yaml" -- set by subclass if AI fallback applies

    def resolve(self, rule_id, pricebook_data, sheet_type):
        if sheet_type in (2, 3):
            return self._resolve_type2_3(rule_id, pricebook_data, sheet_type)
        if not self.has_mapping:
            # BUGFIX: this used to return entries=[] (zero rows), which
            # meant the category never got written at all -- but the
            # template itself has placeholder rows (1, 2, etc.) for every
            # category including no-mapping ones like CAT09, meaning it
            # still expects one row per fare with just the common fields
            # filled in. An empty entries list produces zero rows; a
            # single blank entry produces the expected one row.
            return self._bundle(rule_id, sheet_type, "NO_CATEGORY_MAPPING", [self._blank_entry()])
        return self._resolve_impl(rule_id, pricebook_data, sheet_type)

    def _resolve_type2_3(self, rule_id, pricebook_data, sheet_type):
        """
        Generic Type 2/3 fallback -- lives in base.py because the Yes/No/NA
        branching mechanism is the SAME across every category for these
        sheet types (confirmed: Type 2's "Same as Base Reference Fare"
        column applies identically to every "Rule Categories" row), unlike
        Type 1 where each category has its own logic. No category
        currently overrides this -- CAT01/02/03 are the only ones analyzed
        for Type 2/3 so far, and DataMapping explicitly defers extraction
        for all three ("No request to code these yet"). So for now, every
        category just reflects the Yes/No/NA flag + AltGenRule via
        common_override, with category-specific fields left blank.
        """
        row = pricebook_data.get_type2_row(self.category)
        if row is None:
            return self._bundle(rule_id, sheet_type, "UNRECOGNIZED",
                                 [self._flagged_entry(f"No {self.category} row found in Fare Rules "
                                                       f"(Type {sheet_type})")])

        same_as_base = (row.get("same_as_base") or "").strip().upper()
        entry = {f: None for f in self.output_fields}

        # "NOT APPLICABLE" confirmed equivalent to "NA" -- CAT26/28/29's
        # real Type 2 sample uses this spelled-out form instead of "NA".
        if same_as_base in ("YES", "NA", "NOT APPLICABLE", ""):
            entry["confidence"] = "HIGH"
            entry["flag_reason"] = None
            branch = "SAME_AS_BASE"
        else:  # 'NO' -- override text exists, but no category has a
               # confirmed Type 2/3 extraction rule yet (CAT01/02/03 are
               # explicitly deferred per DataMapping notes)
            entry["confidence"] = "LOW"
            entry["flag_reason"] = (f"Same as Base Reference Fare = 'No' but no Type {sheet_type} "
                                     f"extraction logic exists yet for {self.category}. "
                                     f"Override text: {row.get('override_text')!r}")
            branch = "TYPE2_3_NO_EXTRACTION_YET"

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
        Optional override for a category's Fare Rule(POO) handling, for
        the single-row case (not CAT10-style multi-row, which pipeline.py
        handles separately via AI). Called by pipeline.py ONLY when the
        POO value doesn't start with "FOLLOW " (copy-through already
        handled generically there). Default: None, meaning "no override,
        fall back to blind AI extraction" -- most categories with a
        standalone POO value (e.g. CAT20-23's "NOT APPLICABLE"/notes text)
        have no structured field to put it in anyway (output_fields=[]),
        so the AI fallback naturally produces an empty-but-valid entry.
        Override this when the POO value maps cleanly onto a known field
        (e.g. CAT19's NoDiscount) -- see cat19_children_infant_discounts.py.
        Return an entry dict (matching self.output_fields) or None.
        """
        return None

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        raise NotImplementedError(f"{self.category} resolver must implement _resolve_impl")

    # ---- shared helpers -------------------------------------------------

    def _bundle(self, rule_id, sheet_type, source_branch, entries):
        return {
            "rule_id": rule_id,
            "category": self.category,
            "sheet_type": sheet_type,
            "source_branch": source_branch,
            "entries": entries,
        }

    def _blank_entry(self):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "HIGH"
        entry["flag_reason"] = None
        return entry

    def _flagged_entry(self, reason):
        entry = {f: None for f in self.output_fields}
        entry["confidence"] = "LOW"
        entry["flag_reason"] = reason
        return entry

    def _is_none_condition(self, condition_text):
        """True if the text is one of the known 'no restriction' phrasings."""
        return (condition_text or "").strip().upper() in NONE_PHRASES

    def _ai_extract_entry(self, condition_text, rule_id, label_override=None):
        """
        Calls the shared AI engine using this category's spec file, and
        this category's field labels read straight from the real template
        (via template_schema.py) -- so the AI sees the exact column names
        a human filer would see ("Passenger Type", "MIN Age", ...) instead
        of our internal short key names. Always returns confidence=LOW --
        AI output is never HIGH confidence, per the project's standing rule.

        label_override: optional {field: label} dict that overrides
        specific labels read from the template -- needed when the raw
        template header is ambiguous on its own (e.g. CAT02's day-of-week
        columns are literally headed "M","T","W","T","F","S","S" in the
        spreadsheet -- Tue/Thu both read "T", Sat/Sun both read "S" --
        so those get replaced with full day names before going to AI).
        """
        spec_path = os.path.join(AI_SPECS_DIR, self.ai_spec_file)
        fare_context = {"rule_id": rule_id, "category": self.category}

        field_labels = {}
        if os.path.exists(TEMPLATE_PATH):
            from template_writer import COLS_BY_CATEGORY
            cols_map = COLS_BY_CATEGORY.get(self.category, {})
            field_labels = get_field_labels(TEMPLATE_PATH, self.category, cols_map)
        if label_override:
            field_labels.update(label_override)

        return extract_with_ai(condition_text, fare_context, spec_path, self.output_fields, field_labels)

    def _copy_ai_fields(self, entry, ai_result, field_names):
        """
        Copies each field in `field_names` from ai_result into entry
        (entry[f] = entry[f] or ai_result.get(f) -- a pre-existing
        deterministic value always wins, same as every call site already
        did by hand), while tracking in entry["ai_fields"] exactly which
        fields' FINAL value came from THIS AI call -- i.e. entry[f] was
        empty beforehand AND ai_result actually provided one. Cumulative
        across multiple AI calls on the same entry via set union, not
        overwrite (CAT15 makes two separate AI calls that can both
        contribute to the same entry).

        This is the piece that makes per-CELL AI highlighting possible in
        template_writer.py -- without it, "ai_used=True" only says
        SOMETHING in this row came from AI, not which cell. Every
        category that does WHOLE-entry extraction (entry = self.
        _ai_extract_entry(...), no selective harvesting) doesn't need
        this at all -- ai_engine.py's extract_with_ai() already computes
        ai_fields correctly for that case, since every field it returns
        non-None IS what the resolver keeps.
        """
        ai_fields = entry.setdefault("ai_fields", set())
        for f in field_names:
            was_empty = not entry.get(f)
            entry[f] = entry.get(f) or ai_result.get(f)
            if was_empty and ai_result.get(f) is not None:
                ai_fields.add(f)
        return entry
