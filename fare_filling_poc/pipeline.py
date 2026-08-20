import os
import time
from collections import defaultdict
from common_fields import extract_common_fields
from ai_engine import extract_with_ai
from categories.base import AI_SPECS_DIR
import run_logger
from categories.cat01_eligibility import Cat01Resolver
from categories.cat02_daytime import Cat02Resolver
from categories.cat03_seasonality import Cat03Resolver
from categories.cat04_flightapplication import Cat04Resolver
from categories.cat05_advance_reservations import Cat05Resolver
from categories.cat06_minimum_stay import Cat06Resolver
from categories.cat07_maximum_stay import Cat07Resolver
from categories.cat08_stopovers import Cat08Resolver
from categories.cat09_transfers import Cat09Resolver
from categories.cat10_combinations import Cat10Resolver
from categories.cat11_blackout_dates import Cat11Resolver
from categories.cat12_surcharges import Cat12Resolver
from categories.cat13_accompanied_travel import Cat13Resolver
from categories.cat14_travel_restrictions import Cat14Resolver
from categories.cat15_sales_restrictions import Cat15Resolver
from categories.cat16_penalties import Cat16Resolver
from categories.cat17_hip_mileage import Cat17Resolver
from categories.cat18_ticket_endorsement import Cat18Resolver
from categories.cat19_children_infant_discounts import Cat19Resolver
from categories.cat20_no_mapping import Cat20Resolver
from categories.cat21_no_mapping import Cat21Resolver
from categories.cat22_no_mapping import Cat22Resolver
from categories.cat23_no_mapping import Cat23Resolver
from categories.cat26_no_mapping import Cat26Resolver
from categories.cat27_no_mapping import Cat27Resolver
from categories.cat28_no_mapping import Cat28Resolver
from categories.cat29_no_mapping import Cat29Resolver
from categories.cat31_voluntary_changes import Cat31Resolver
from categories.cat33_no_mapping import Cat33Resolver

CATEGORY_REGISTRY = [
    Cat01Resolver(),
    Cat02Resolver(),
    Cat03Resolver(),
    Cat04Resolver(),
    Cat05Resolver(),
    Cat06Resolver(),
    Cat07Resolver(),
    Cat08Resolver(),
    Cat09Resolver(),
    Cat10Resolver(),
    Cat11Resolver(),
    Cat12Resolver(),
    Cat13Resolver(),
    Cat14Resolver(),
    Cat15Resolver(),
    Cat16Resolver(),
    Cat17Resolver(),
    Cat18Resolver(),
    Cat19Resolver(),
    # CAT24, 30, 32 don't exist in ATPCO's numbering (confirmed gap).
    # CAT25 (Fare By Rule) exists in Fare Rules text but has NO
    # corresponding block in the real template at all -- skipped
    # entirely, nowhere to write it even if resolved.
    Cat20Resolver(),
    Cat21Resolver(),
    Cat22Resolver(),
    Cat23Resolver(),
    Cat26Resolver(),
    Cat27Resolver(),
    Cat28Resolver(),
    Cat29Resolver(),
    Cat31Resolver(),
    Cat33Resolver(),
]


def run_pipeline(anchor_rows, pricebook_lookup):
    """
    anchor_rows: list of dicts {"RULE", "TARIFF", "PRICEBOOK_NAME", "sheet_type"}
                 (this is what the future upload form will produce)
    pricebook_lookup: dict of RULE -> PricebookData

    IMPORTANT DESIGN NOTE: output is organized PER CATEGORY, matching the
    real target file (separate CAT1-CAT33 sheets in the FINAL TEMPLATE),
    not merged into one wide row per fare. Each category's rows carry
    their own copy of the common fields, same as every scheme we analyzed
    shows a "PRICEBOOK NAME / RULE / TARIFF / MARKETS..." block repeated
    at the start of every category's columns.

    Returns: {
        "CAT01": [row, row, ...],
        "CAT02": [...],
        "CAT03": [...],
        "CAT04": [...],
        "CAT04_CarrierTableNo1": [...],   # supporting table, only present
                                            # for categories that have one
    }
    """
    grouped = defaultdict(list)
    for anchor in anchor_rows:
        grouped[anchor["RULE"]].append(anchor)

    output = defaultdict(list)

    for rule_id, tariff_anchors in grouped.items():
        pricebook_data = pricebook_lookup[rule_id]
        sheet_type = tariff_anchors[0]["sheet_type"]  # same for every TARIFF of this RULE

        run_logger.log(f"[pipeline] RULE={rule_id}: resolving {len(CATEGORY_REGISTRY)} categories...")

        for resolver in CATEGORY_REGISTRY:
            t0 = time.time()
            bundle = resolver.resolve(rule_id, pricebook_data, sheet_type)
            category = bundle["category"]
            elapsed = time.time() - t0
            # Only log categories that took a noticeable amount of time
            # (i.e. an AI call happened inside resolve()) -- deterministic
            # categories resolve near-instantly and would just be noise.
            if elapsed > 0.5:
                run_logger.log(f"[pipeline] RULE={rule_id} {category} resolved "
                                f"(branch={bundle['source_branch']}, {elapsed:.2f}s)")

            # cross-join: this category's entries x every TARIFF for this RULE
            common_override = bundle.get("common_override", {})
            for tariff_anchor in tariff_anchors:
                common = extract_common_fields(tariff_anchor, pricebook_data, category)
                for entry in bundle["entries"]:
                    row = {**common, **common_override, "source_branch": bundle["source_branch"], **entry}
                    output[category].append(row)

            # supporting tables (e.g. CAT04's Carrier Table No.1) also
            # get cross-joined across TARIFF, same as the main entries
            for table_name, table_rows in bundle.get("supporting_tables", {}).items():
                key = f"{category}_{table_name}"
                for tariff_anchor in tariff_anchors:
                    common = extract_common_fields(tariff_anchor, pricebook_data, category)
                    for trow in table_rows:
                        output[key].append({**common, **trow})

    return dict(output)


def run_pipeline_type2_3(anchor_rows, pricebook_lookup):
    """
    Type 2/3 variant. Each RULE's pricebook_lookup entry is a tuple
    (main_pricebook, poo_pricebook) from xlsm_loader.load_pricebook_type2().

    Resolves every category against the main "Fare Rules" pricebook first
    (via the normal run_pipeline() machinery), then separately resolves
    against "Fare Rule(POO)": if POO's value is "FOLLOW BASE FARE"
    (confirmed to mean "copy whatever Fare Rules resolved for this same
    category"), the main sheet's row is copied over verbatim; there's no
    confirmed extraction rule yet for any other POO value.

    Returns (output_main, output_poo) -- two dicts in the same shape as
    run_pipeline()'s return value, meant to be written to two separate
    sheets in the output workbook (template_writer.write_to_template_type2).
    """
    main_lookup = {rule: pb[0] for rule, pb in pricebook_lookup.items()}
    output_main = run_pipeline(anchor_rows, main_lookup)

    grouped = defaultdict(list)
    for anchor in anchor_rows:
        grouped[anchor["RULE"]].append(anchor)

    output_poo = defaultdict(list)
    for rule_id, tariff_anchors in grouped.items():
        _, poo_pricebook = pricebook_lookup[rule_id]
        if poo_pricebook is None:
            continue  # this file has no Fare Rule(POO) sheet

        for resolver in CATEGORY_REGISTRY:
            category = resolver.category
            poo_subrows = poo_pricebook.get_type2_subrows(category)

            if poo_subrows:
                # Multi-row category in POO too (confirmed for CAT10) --
                # no clean single "value" to compare against "FOLLOW BASE
                # FARE", and the text is confirmed to sometimes genuinely
                # differ from the main sheet (CAT10's Open-Jaw clause
                # drops "AND RULE <...>" in POO). Per project decision:
                # route straight to AI rather than guessing a rule.
                combined_text = "\n".join(
                    f"{label}: {row.get('override_text') or row.get('poo_value') or '(not specified)'}"
                    for label, row in poo_subrows.items()
                )
                entry = _ai_fallback_entry(resolver, combined_text, rule_id)
                for tariff_anchor in tariff_anchors:
                    common = _build_type2_common(tariff_anchor, None)
                    output_poo[category].append({**common, **entry})
                continue

            poo_row = poo_pricebook.get_type2_row(category)
            if poo_row is None:
                continue
            poo_value = (poo_row.get("poo_value") or "").strip().upper()

            for tariff_anchor in tariff_anchors:
                if _is_follow_through(poo_value):
                    # find the matching main-sheet row for this exact
                    # RULE+TARIFF (main output already has one row per
                    # TARIFF per category -- pick the one matching this anchor)
                    matches = [r for r in output_main.get(category, [])
                               if r["RULE"] == tariff_anchor["RULE"] and r["TARIFF"] == tariff_anchor["TARIFF"]]
                    if matches:
                        output_poo[category].append(dict(matches[0]))
                else:
                    # Not a "FOLLOW ..." copy-through phrase -- try the
                    # resolver's own POO logic first (e.g. CAT19 maps this
                    # straight onto NoDiscount), falling back to AI only
                    # if the resolver doesn't have a specific rule for it.
                    override_entry = resolver.resolve_poo_single(poo_row, rule_id)
                    if override_entry is not None:
                        entry = {**override_entry, "source_branch": "POO_TYPE2_3_EXTRACTED"}
                    else:
                        entry = _ai_fallback_entry(resolver, poo_row.get("poo_value") or "", rule_id)
                    common = _build_type2_common(tariff_anchor, poo_row.get("alt_gen_rule"))
                    output_poo[category].append({**common, **entry})

    return output_main, dict(output_poo)


def _is_follow_through(poo_value):
    """
    "FOLLOW BASE FARE" and "FOLLOW REQUESTING STATION CAT14. TRAVEL DATES
    PER ABOVE" are confirmed functionally equivalent (both mean "copy
    whatever Fare Rules resolved for this same category") despite
    different wording -- so any "FOLLOW ..." phrase is treated as a
    copy-through signal, not just the exact "FOLLOW BASE FARE" string.
    Same principle as base.py's NONE_PHRASES for the "no restriction"
    case: recognize the pattern, not one fixed phrase.
    """
    return poo_value.startswith("FOLLOW ")


def _build_type2_common(tariff_anchor, alt_gen_rule):
    # extract_common_fields() assumes a Type-1-shaped PricebookData
    # internally (for IPRG lookup) -- doesn't apply to Type 2/3 POO rows,
    # so common fields are built directly here instead.
    clean_iprg = alt_gen_rule if alt_gen_rule not in (None, "-") else None
    return {
        "PRICEBOOK NAME": tariff_anchor["PRICEBOOK_NAME"],
        "SAME AS BASE REFERENCE FARE ?": None,
        "RULE": tariff_anchor["RULE"],
        "TARIFF": tariff_anchor["TARIFF"],
        "AltGenTariff": "IPRG" if clean_iprg else None,
        "AltGenRule": clean_iprg,
        "OW/RT": None,
    }


def _ai_fallback_entry(resolver, text, rule_id):
    if not resolver.ai_spec_file:
        return {
            "source_branch": "POO_NO_EXTRACTION_YET",
            "confidence": "LOW",
            "flag_reason": f"Fare Rule(POO) text doesn't match 'FOLLOW BASE FARE' and {resolver.category} "
                            f"has no ai_spec_file configured yet -- text: {text!r}",
        }
    spec_path = os.path.join(AI_SPECS_DIR, resolver.ai_spec_file)
    result = extract_with_ai(text, {"rule_id": rule_id, "category": resolver.category},
                              spec_path, resolver.output_fields)
    result["source_branch"] = "POO_AI_EXTRACTED"
    return result
