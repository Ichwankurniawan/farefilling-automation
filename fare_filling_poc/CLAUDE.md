# Fare Filling Automation — Project Context

This file is meant to be read by Claude Code (or any future session/developer)
picking up this project cold. It captures the architecture decisions,
per-category mapping status, bugs already found & fixed, and open items —
everything that would otherwise only live in chat history.

**Read this before touching `template_writer.py` or adding a new category
resolver.** Several non-obvious bugs (documented below) have already been
found and fixed once; the reasoning is preserved here so they don't get
reintroduced.

---

## 1. What this project does

Reads airline fare-filing pricebook files (`.xlsm`), interprets each fare
category's rule text (deterministic where possible, AI where the text is
genuinely free-form), and writes the result into the airline's real Excel
filing template (`SQ_Fare_Filling_Template.xlsx`). Also emits a parallel
JSON output for downstream AI/automation integration.

## 2. Pipeline architecture

```
Web upload form (webapp/, see section 15) OR run_new_filing.py CLI
  -> General Value / anchor rows: (RULE, TARIFF, PRICEBOOK NAME, sheet_type)
  -> Group anchor rows by RULE (one RULE can have multiple TARIFFs)
  -> For each RULE: resolve every category once (CATEGORY_REGISTRY, in
     numeric order), then cross-join the result across every TARIFF
     belonging to that RULE
  -> Output organized PER CATEGORY (dict of "CAT01" -> [rows], matching
     the real template's per-category blocks, NOT one merged row)
  -> template_writer.py writes each category's rows into the real
     template at verified cell coordinates
```

Key insight: **one pricebook file = one RULE**, but a RULE can have
multiple TARIFFs (entered via the upload form or CLI, along with
`sheet_type`). Fare Rules / category tabs are defined once per RULE;
the pipeline cross-joins that once-per-RULE data across every TARIFF.

## 3. Category resolver decision tree

Every resolver follows this order before falling back to AI:

```
1. Does this category have ANY field-level DataMapping?
   NO  -> has_mapping=False -> common fields only, no extraction
          (verified per-category against the REAL template structure,
          not inferred from documentation -- e.g. CAT09 genuinely has
          no RI/Table/CAT columns at all)
   YES -> continue

2. Does the category have a structured "Need to refer to another tab?"
   flag column (CAT01/02), or a "REFER TO ..." text pattern (CAT03-07, 10)?
   YES -> deterministic lookup / regex parse
   NO  -> continue

3. Is the condition text exactly "NONE UNLESS OTHERWISE SPECIFIED"?
   YES -> blank entry, confidence=HIGH
   NO  -> continue

4. Is there an EXPLICIT IF/THEN extraction rule given for this text
   pattern (e.g. CAT04's "Except:"/"OPERATED BY" parsing, CAT10's
   "ANY TARIFF"/"ANY RULE" regex)?
   YES -> deterministic regex, confidence=HIGH
   NO  -> AI fallback (ai_specs/catXX_spec.yaml), confidence=LOW,
          flag_reason set
```

**Important correction already made once:** AI must NOT be triggered for
the "NONE UNLESS OTHERWISE SPECIFIED" branch -- only for genuinely
unmatched free text. An earlier version of this code mistakenly routed
step 3 through AI; this was reverted.

**Second correction already made once:** even for categories where
`has_mapping=False` (or all mapped fields are deterministic), if there's
ANY leftover free text with no rule (e.g. CAT09's whole condition, CAT10's
"Side Trips"/"Notes" sub-rows), don't leave it as a silent TODO -- route it
through AI too, even if the result only lives in the JSON output (no
Excel column exists for it, e.g. CAT09's `Note` field).

## 4. AI extraction architecture

Two things feed into every AI call, from two different real sources:

| Source | Sheet | Feeds into | Called at runtime? |
|---|---|---|---|
| `template_schema.py` | `(FINAL TEMPLATE) CAT 1-CAT 33` | Field labels shown to the AI (e.g. "Passenger Type", not `PassengerType`) -- read directly from the template's own header cells | **Yes**, every AI call |
| `data_mapping_final.json` | `Data Mapping` (user's `Final_Data_Mapping.xlsx`) | Manually referenced when writing `ai_specs/*.yaml` instructions or checking a new category's Type 1/2/3 mapping before asking the user again | **No** -- deliberately not wired into code, kept as a reference file only. Supersedes the older `data_mapping_parsed.json` (removed during cleanup -- see section 8) |

```
ai_specs/catXX_spec.yaml (category instruction + few-shot)
        |
base.py -- _ai_extract_entry() (loads spec + field labels for this category)
        |
ai_engine.py -- extract_with_ai() (builds prompt, calls the LLM, parses JSON)
        |
  AI_PROVIDER=anthropic + ANTHROPIC_API_KEY set?      -> real Claude API call
  AI_PROVIDER=openai_compatible + AI_BASE_URL/AI_MODEL set? -> real call to a
                                                          self-hosted/OpenAI-
                                                          compatible endpoint
  neither configured?                                  -> mock response,
                                                          clearly labeled,
                                                          NOT a real result
        |
Entry returned with confidence="LOW", flag_reason set
        |
run_logger.record_ai_call() -- logs provider/model/elapsed time/token usage
for every attempt (real, mock, or failed) -- see section 14
```

**Two AI providers are supported, chosen by `AI_PROVIDER` env var** (real
production use is via the second one -- no `ANTHROPIC_API_KEY` is
available in this environment; the model runs on a self-hosted Linux
server instead):
- `AI_PROVIDER=anthropic` -- needs `ANTHROPIC_API_KEY`. Never actually
  exercised end-to-end with a real key in this project so far.
- `AI_PROVIDER=openai_compatible` -- needs `AI_BASE_URL` + `AI_MODEL`,
  `AI_API_KEY` optional (the self-hosted endpoint needs none). **This is
  the path actually used and verified** -- confirmed end-to-end against a
  self-hosted `qwen3.6:35b-a3b-uncensored` model at
  `http://10.90.10.20:8081/v1`, real runs, real tokens, real timing.

Config is loaded from `ai_config.env` (KEY=VALUE lines, gitignored-style
local file, not committed), auto-loaded once via `ai_engine.py`'s
`_load_ai_config()` using `os.environ.setdefault()` -- so a real env var
always wins over the file, and nothing needs to be manually exported
before running. Current values:
```
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://10.90.10.20:8081/v1
AI_MODEL=qwen3.6:35b-a3b-uncensored
AI_MAX_TOKENS=4000
```

**Reasoning models need a much higher `max_tokens` than a normal chat
model.** The self-hosted Qwen model emits a separate internal `reasoning`
field that consumes completion tokens BEFORE the final JSON answer.
`DEFAULT_MAX_TOKENS` was originally hardcoded `500` (fine for a
non-reasoning model), which silently truncated every real call
(`finish_reason: "length"`, empty final content) once switched to this
model. Fixed: `DEFAULT_MAX_TOKENS` now reads from `AI_MAX_TOKENS`
(default `4000` if unset). **Ordering matters here**: `_load_ai_config()`
must run BEFORE `DEFAULT_MAX_TOKENS` is computed at module import time --
an early version of this fix had the config-file load happen after the
constant was already read from `os.environ`, so `AI_MAX_TOKENS` set only
in `ai_config.env` (not a real env var) silently had no effect.

### `categories/base.py` (full file)

```python
"""
Base class every category resolver inherits from.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai_engine import extract_with_ai
from template_schema import get_field_labels

AI_SPECS_DIR = os.path.join(os.path.dirname(__file__), "..", "ai_specs")
TEMPLATE_PATH = "/home/claude/SQ_Fare_Filling_Template__1_.xlsx"


class CategoryResolver:
    category = None          # e.g. "CAT01"
    has_mapping = True
    output_fields = []
    ai_spec_file = None

    def resolve(self, rule_id, pricebook_data, sheet_type):
        if not self.has_mapping:
            # has_mapping=False still returns ONE blank entry, not zero --
            # the template expects a row (even if just common fields) per
            # fare. entries=[] used to be a bug that silently produced
            # zero output rows for e.g. CAT09.
            return self._bundle(rule_id, sheet_type, "NO_CATEGORY_MAPPING", [self._blank_entry()])
        return self._resolve_impl(rule_id, pricebook_data, sheet_type)

    def _resolve_impl(self, rule_id, pricebook_data, sheet_type):
        raise NotImplementedError(f"{self.category} resolver must implement _resolve_impl")

    def _bundle(self, rule_id, sheet_type, source_branch, entries):
        return {
            "rule_id": rule_id, "category": self.category,
            "sheet_type": sheet_type, "source_branch": source_branch,
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

    def _ai_extract_entry(self, condition_text, rule_id):
        spec_path = os.path.join(AI_SPECS_DIR, self.ai_spec_file)
        fare_context = {"rule_id": rule_id, "category": self.category}

        field_labels = {}
        if os.path.exists(TEMPLATE_PATH):
            from template_writer import COLS_BY_CATEGORY
            cols_map = COLS_BY_CATEGORY.get(self.category, {})
            field_labels = get_field_labels(TEMPLATE_PATH, self.category, cols_map)

        return extract_with_ai(condition_text, fare_context, spec_path, self.output_fields, field_labels)
```

**Since this snippet was written**: `TEMPLATE_PATH` is no longer the
hardcoded `/home/claude/...` sandbox path shown above -- it's now a
relative path (`template/SQ Fare Filling Template.xlsx`, resolved from
the project root) so the project runs on any machine, not just the
original sandbox. `base.py` also now imports `_lookup_owrt_type23` from
`common_fields.py` and injects it into `_resolve_type2_3()`'s
`common_override` -- see section 13.

### `ai_engine.py` (key parts)

```python
"""
Generic AI-extraction engine, shared by every category resolver.
One engine builds the prompt, calls the LLM, and parses the JSON
response. Category-specific knowledge lives in ai_specs/*.yaml, not here.
"""
import json
import os
import yaml

MODEL = "claude-sonnet-4-5"


def extract_with_ai(condition_text, fare_context, spec_path, output_fields, field_labels=None):
    spec = _load_spec(spec_path)
    prompt = _build_prompt(condition_text, fare_context, spec, output_fields, field_labels or {})

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _mock_response(output_fields, reason="No ANTHROPIC_API_KEY set -- mock response, not a real AI call")

    try:
        raw = _call_claude(prompt, api_key)
        parsed = _parse_json_response(raw, output_fields)
        parsed["confidence"] = "LOW"
        parsed["flag_reason"] = "AI-extracted from free text -- needs human review"
        return parsed
    except Exception as e:
        return _mock_response(output_fields, reason=f"AI call failed ({e}) -- fell back to blank, flagged")


def _build_prompt(condition_text, fare_context, spec, output_fields, field_labels):
    # Shows the AI the exact template column label per field (from
    # template_schema.py), not our internal short key names.
    field_lines = []
    for f in output_fields:
        label = field_labels.get(f)
        if label:
            field_lines.append(f'  "{f}": null   // template column label: "{label}"')
        else:
            field_lines.append(f'  "{f}": null')
    schema_block = "{\n" + ",\n".join(field_lines) + "\n}"

    return f"""You are extracting structured fare-filing data from an airline fare rule's condition text.

Category: {spec['category']}
Instruction: {spec['instruction']}

Fare context: {json.dumps(fare_context, indent=2)}

Condition text to interpret:
\"\"\"{condition_text}\"\"\"

Output ONLY a JSON object with exactly these fields:
{schema_block}
"""

# _call_claude(), _parse_json_response(), _mock_response() -- see ai_engine.py directly
```

**Since this snippet was written**: `_call_claude()` and
`_call_openai_compatible()` (new -- the `openai_compatible` provider
path) both return `(text, usage_dict)` tuples instead of just text,
capturing `prompt_tokens`/`completion_tokens`/`total_tokens` (normalized
across Anthropic's `input_tokens`/`output_tokens` and OpenAI's native
field names). `extract_with_ai()` calls `run_logger.record_ai_call(...)`
for every real/mock/error attempt -- see section 14 for what that logs.

### Every AI-derived result is `confidence="LOW"` -- never HIGH

This is a hard rule across the whole project, whether the result came
from a real API call or the no-key mock. If a category needs mixed
confidence (some fields deterministic HIGH, some AI-derived LOW), the
convention is: **downgrade the whole entry to LOW** rather than trying to
track confidence per-field (see CAT10's Side Trips/Notes handling).

---

## 5. File structure

```
fare_filling_poc/
|-- pricebook_data.py         # Type 1: wraps Fare Rules + tab data; get_fare_rules_row(),
|                              # get_fare_rules_rows() (multi-condition-line cats),
|                              # get_fare_rules_subrows() (CAT10-style sub-row cats)
|-- pricebook_data_type2.py   # Type 2/3: PricebookDataType2 (one row or list of
|                              # sub-rows per category); shared by both Type 2 and
|                              # Type 3 via xlsm_loader's synthesis (see section 11)
|-- xlsm_loader.py             # reads real XLSM files -- KEYWORD-BASED header
|                              # detection (find_header_row) for all 3 types, NOT
|                              # "row 1 is header". load_pricebook_from_xlsm() (Type 1),
|                              # load_pricebook_type2(), load_pricebook_type3()
|-- common_fields.py           # Type 1 shared fields (PRICEBOOK NAME, RULE, TARIFF,
|                              # AltGenTariff, AltGenRule) -- IPRG code is PER-CATEGORY,
|                              # must pass `category` param (see bug #3). Type 2/3 use
|                              # bundle["common_override"] instead (see section 10).
|                              # Also: _lookup_owrt() (Type 1 OW/RT, from the "Output"
|                              # tab) and _lookup_owrt_type23() (Type 2/3 OW/RT, from
|                              # the Edifact/NDC/Faresheet data sheet) -- see section 13
|-- run_logger.py              # separate from JSON/xlsx output on purpose -- progress
|                              # logging + per-AI-call timing/token-usage tracking +
|                              # end-of-run summary. set_log_file(), log(),
|                              # record_ai_call(), log_summary()
|-- run_new_filing.py          # CLI entry point for running the pipeline against NEW
|                              # real pricebook files (not the synthetic test fixtures)
|                              # -- see section 14, "How to run"
|-- ai_config.env              # AI_PROVIDER/AI_BASE_URL/AI_MODEL/AI_MAX_TOKENS --
|                              # local config, auto-loaded by ai_engine.py, not a real
|                              # env var export needed (see section 4)
|-- pipeline.py                # CATEGORY_REGISTRY (numeric order). run_pipeline()
|                              # (Type 1, also used as Type 2/3's main-sheet resolution)
|                              # and run_pipeline_type2_3() (adds Fare Rule(POO) handling)
|-- template_columns.py        # WHERE each field lives: every CATxx_COLS dict,
|                              # CATxx_START_ROW, COLS_BY_CATEGORY -- pure data,
|                              # read directly from the template, no writing logic.
|                              # Split out of template_writer.py so "where does a
|                              # field live" and "how do we write it" can be read
|                              # and changed independently -- imported wholesale via
|                              # `from template_columns import *` (__all__-pinned),
|                              # so `from template_writer import COLS_BY_CATEGORY`
|                              # (categories/base.py) keeps working unchanged.
|-- template_writer.py         # HOW we write it: dynamic row-shifting/capacity,
|                              # style preservation, output value normalization
|                              # (_normalize_output_value -- bug #25), per-cell AI
|                              # highlighting. write_to_template() (Type 1, one
|                              # sheet) and write_to_template_type2() (Type 2/3,
|                              # duplicates the sheet for POO output)
|-- template_schema.py         # reads field labels from the real template's own
|                              # header cells (CATEGORY_HEADER_ROWS)
|-- ai_engine.py                # generic AI call, one implementation
|-- ai_specs/                   # per-category instruction + few-shot (yaml) --
|                              # only exists where actually used or genuinely
|                              # plausible later (see the AI spec coverage policy
|                              # in section 4)
|-- categories/
|   |-- base.py                 # CategoryResolver base class -- has_mapping check,
|   |                          # generic _resolve_type2_3() fallback + resolve_poo_single()
|   |                          # hook, NONE_PHRASES, shared AI-call helper
|   `-- cat01_eligibility.py ... cat33_no_mapping.py   # one file per implemented category
|-- data_mapping_final.json    # authoritative reference (all CAT01-33, Type1/2/3
|                              # columns) parsed from the user's Final_Data_Mapping.xlsx --
|                              # reference only, NOT called by any code (by design)
|-- CLAUDE.md                   # this file
|-- test_from_real_files.py    # Type 1 end-to-end (real XLSM -> real template)
|-- test_ai_fallback_e2e.py    # proves the AI-fallback branch really fires
|-- test_type2.py               # Type 2 end-to-end (main + POO, two output sheets)
`-- test_type3.py               # Type 3 end-to-end (main + POO, two output sheets)
```

**A real `tests/` pytest suite now exists too, at the project root** (sibling
to `fare_filling_poc/` and `webapp/`, not inside either) -- unrelated to
the broken `test_from_real_files.py`/`test_type2.py`/`test_type3.py`
above (those stay real-file end-to-end tests, whenever their fixtures get
regenerated; `tests/` is fast, synthetic-data unit tests, run in CI on
every push via `.gitlab-ci.yml`'s `unit-tests` job):

```
tests/
|-- conftest.py             # sys.path setup -- same pattern every real entry
|                          # point already uses, no installed package exists
|-- test_template_writer.py # _parse_date_value(), _normalize_output_value()
|                          # (bug #25)
|-- test_intake_matcher.py  # _looks_like_rule_code() (bug #28),
|                          # normalize_rule_and_tariffs(), _parse_rule_tariff_text()
|-- test_category_base.py   # _copy_ai_fields() (section 12's per-cell highlighting)
|-- test_ratelimit.py       # webapp/ratelimit.py's exact boundary
|-- test_jobs_queue.py      # webapp/jobs.py's get_queue_position()
`-- test_xlsm_loader.py     # _normalize_cat_number(), _sheet_to_rows()'s
                           # blank-row early-exit (bug #29)
```

Run locally with `fare_filling_poc/.venv/Scripts/python.exe -m pytest tests/ -v`
from the project root (pytest itself is deliberately not added to
`fare_filling_poc/requirements.txt` -- installed inline in CI, same as
`playwright` for the smoke test, to keep the production dependency list
free of test-only tooling).

Sibling directories, each with their own generator script producing the
XLSM inputs the test scripts above read:
- `input_files/` (Type 1) -- `build_pricebooks.py` -> `V1-ABC1 Type1.xlsm`, `V1-ABC2 Type1.xlsm`
- `input_files_type2/` -- `build_pricebooks_type2.py` -> `V1-ABC1-Type2.xlsm`, `V2-ABC2-Type2.xlsm`
- `input_files_type3/` -- `build_pricebooks_type3.py` -> `V1-DEF1-Type3.xlsm`, `V1-DEF2-Type3.xlsm`

**Known issue, discovered this session**: `input_files_type2/` and
`input_files_type3/` no longer exist on disk, and `input_files/` now
holds real production pricebook files (HKF1/HKF2, Cargolux, Tianqi)
instead of the original synthetic `V1-ABC1 Type1.xlsm`/`V1-ABC2
Type1.xlsm`. This means `test_from_real_files.py`, `test_type2.py`, and
`test_type3.py` currently fail with `FileNotFoundError` -- confirmed NOT
caused by any code change in this session, the folders/files were simply
removed or reorganized outside of it. All real verification this session
was done directly against the real files in `input_files/` via
`run_new_filing.py` (see section 14) or inline scripts instead. If these
regression scripts are needed again, the synthetic fixtures need
regenerating via their `build_pricebooks*.py` scripts first.

**Removed during cleanup** (obsolete/superseded, kept in git history only if
needed later): `test_run.py` + `run_and_export.py` (dict-mock-based, from
before real XLSM reading existed -- fully superseded by
`test_from_real_files.py`), `test_ai_prompt.py` (isolated demo, superseded
by the fuller `test_ai_fallback_e2e.py`), `rule_tariff_table.py` (dead code
once `test_run.py` was removed -- `template_writer.py` has its own internal
`_write_rule_tariff_table()`, unrelated), `data_mapping_parsed.json`
(superseded by `data_mapping_final.json`), and stale generated `.xlsx`/
`.pdf`/`.json` artifacts in the project root (regenerate on demand by
running the test scripts).

| Cat | Name | Status | Branch pattern |
|---|---|---|---|
| 01 | Eligibility | Coded | 3-branch: NONE / REFER-YES (lookup) / REFER-NO (parse override text) / else AI |
| 02 | Day/Time | Coded | 2-branch: NONE or REFER-NO = blank / REFER-YES (lookup) / else AI |
| 03 | Seasonality | Coded | Text-pattern (no flag column): NONE / REFER-YES (row-expansion from tab) / else AI. **FIXED (real-file bug)**: `CAT03-Seasonality` has a two-row header identical in shape to CAT11's -- the generic single-row reader picked the GROUP row (its merged "SEASONALITY DATES" cell coincidentally contains keyword "SEASONALITY"), leaking the sub-header row in as bogus data and dropping `FareClassFamily`/`FirstDate`/`LastDate`/`SeasonType` to `None` on EVERY row silently. Now has its own `_read_cat03_seasonality()` two-row reader (see section 7). `FareClassFamily`/dates now looked up by keyword, not exact string (real header has an embedded newline: `"FARE BASIS /\nFARE CLASS FAMILY"`). `"All"`/3-letter codes -> LOC1/LOC2 (not Zone). `OW/RT` now resolved per-row from the "Output" tab via `FareClassFamily` (see section 13) instead of always `None` |
| 04 | Flight Application | Coded | Direction-based row expansion (Outbound/Inbound), "Except:" clause parsing, Carrier Table No.1 supporting table. **Confirmed constants/fixes**: `Table` always `"NEW"`; `Flight1` always `"SQ"` (previously wrongly hardcoded `"GA"`, traced to this project's own synthetic test data using Garuda Indonesia as the example carrier); `"All"` classifies as LOC (not Zone); `OW/RT` resolved per-row from the "Output" tab via `FareClassFamily` (see section 13). Handles THREE real tab shapes for `CAT04-FlightApplication`: two-row header w/ OUTBOUND/INBOUND split (`_read_cat04_flight_application()`), single "FLIGHT APPLICATION" column w/ no direction split (`_read_cat04_flight_application_single_column()`, applies the same text to both O/I), and generic single-row fallback |
| 05 | Advance Reservations | Coded | Reads shared `CAT050607` tab's ADV PURCHASE columns. **FIXED**: same `FareClassFamily` keyword-lookup + `"All"`-as-LOC + per-row `OW/RT` fixes as CAT03/04 (see section 13) -- was previously always `None` on real files (exact-string lookup didn't match the real embedded-newline header) |
| 06 | Minimum Stay | Coded | Reads `CAT050607`'s MIN STAY columns; Measured/Return-Travel-From TSI constants. **FIXED**: same `FareClassFamily`/LOC/`OW/RT` fixes as CAT05 |
| 07 | Maximum Stay | Coded | Reads `CAT050607`'s MAX STAY columns -- user's DataMapping text said "MIN STAY" (likely copy-paste error), flagged LOW pending confirmation. **FIXED**: same `FareClassFamily`/LOC/`OW/RT` fixes as CAT05/06 |
| 08 | Stopovers | Coded | Has a REFER-TO branch (same pattern as CAT03/04/05) but no real sample has ever exercised it -- every real file's text is self-contained prose, so it always falls to AI (`Max Permitted` keyword, `No Charge` inferred from "FREE"). **FIXED (bug #30)**: now short-circuits on "NONE UNLESS OTHERWISE SPECIFIED" before the AI branch -- previously absent, which let a real AI call misread that phrase as `MaxPermitted="NONE"` |
| 09 | Transfers | Coded | `has_mapping=True` but produces only a JSON-only `Note` field via AI -- verified directly against template: NO Excel columns exist for this category at all |
| 10 | Permitted Combinations | Partial | Sub-row Fare Rules structure (new pattern). Circle Trip/End-on-End/Open-Jaw/Qualifying-106/107 deterministic (explicit IF/THEN rules given); Side Trips/Notes via AI. **Tables 101/102/104's own "Application Tags" columns (AI/AK/AM/AP) are implemented** -- confirmed by reading the real template directly: these ARE `SingleOpenJaw`/`DoubleOpenJaw`/`CircleTripPermitted`/`EndOnEndPermitted`, just displayed a second time in this summary row band (row 97-98) as well as the main block. **Table 103's own "Permitted" column (AN) was genuinely missing** (not a bug -- `CAT10_COLS` simply never had an entry for it) until found via direct template inspection + a real user-provided example showing both columns holding the identical value; fixed by mirroring `CircleTripPermitted` into it at write time (`template_writer.py`'s `SIMPLE_CATEGORIES_PART1` loop, not in the resolver -- keeps `CAT10`'s AI schema/`output_fields` untouched, and applies uniformly to both the main sheet and the POO sheet's independently-resolved value). The mirrored cell's AI highlight is propagated too (found by testing, not assumed -- the mirror initially copied the value but not the yellow "needs review" fill, which would have made table 103 look more certain than table 102's identical, correctly-highlighted value next to it). **Record 3 Tables' remaining columns** (`AJ` Origin/Destination, `AL`/`AO` OW-Fare-Allowed) **and Qualifying 108/109 still not implemented** -- no known source cell for these, unlike table 103 above. |
| 11 | Blackout Dates | Coded | Text-pattern: NONE / REFER-YES (row-expansion from `CAT11-Blackouts` tab, same LOC-vs-Zone pattern as CAT03) / else AI. **FIXED**: tab has a real TWO-row header (like CAT050607) -- `_read_cat11_blackouts()` now handles it correctly. `Day/Range = "Range"` when both Date1/Date2 present (confirmed). **Also FIXED this session**: same `FareClassFamily` keyword-lookup + `"All"`-as-LOC + per-row `OW/RT` fixes as CAT03/04/05/06/07 |
| 12 | Surcharges | Skeleton only | REFER TO detected but no `CAT12-Surcharges` tab sample/mapping exists yet. `SurchargeType` deliberately left empty. Charge Information + both Applies-To geo blocks entirely unmapped |
| 13 | Accompanied Travel | Coded | `has_mapping=False`, verified via template: no category-specific columns exist at all |
| 14 | Travel Restrictions | Skeleton | Only OW/RT + common fields. `On/After`/`On/Before (Commence)` explicitly deferred by DataMapping ("no request to code these yet for Type 1") -- kept as real output fields, always None |
| 15 | Sales Restrictions | Coded | Combines AI (Location1-3 Type/Value/Exclude + 7 Ticketing-mode flags, from main condition text + "Ticketing Mode" sub-row) with deterministic lookup. **CORRECTED**: only `TicketMustBeIssuedOn*` comes from Filing Instructions "Sales From/To" -- `ReservationMustBeOn*` stays empty (an earlier version wrongly populated both from the same source). New: `pricebook_data.get_filing_instruction()` + `xlsm_loader._read_filing_instructions()` (key-value shaped tab, not row-based) |
| 16 | Penalties | Coded (partial) | **IMPLEMENTED**: "Notes" sub-row (real, extractable service-fee text, confirmed identical shape on HKF1/HKF2) now routes through AI into 7 grounded fields (ChargeAmt1/ChargeCur1/AppliesPer/ChargeAppliesToReissue/ChargeAppliesToRevalidation/ChargeAppliesToRefund/NoteText). "Voluntary Change/Refund/No show" is deliberately NEVER read -- confirmed on every real sample to be a bare pointer to an unseen external "FARE FAMILY FEE CONDITIONS" document, not real content. The other 27 of the template's 34 real category-specific columns (Before/After Departure, Charge Type VOL/INVOL/Cancel, all 6 Waivers fields, Override Date, etc.) have no textual grounding in any real sample seen so far and are deliberately left unmapped rather than guessed |
| 17 | HIP/Mileage Exceptions | Coded | Reason `NONE_PHRASES`/`_is_none_condition()` was added to base.py: sample condition is "UNLESS OTHERWISE SPECIFIED DOES NOT APPLY", a different phrasing than the usual exact-match -- both are now recognized as "no restriction" |
| 18 | Ticket Endorsement | Coded | `has_mapping=False` -- confirmed since the very start of this project (rich-looking text, but DataMapping explicitly says no field-level mapping exists) |
| 19 | Children/Infant Discounts | Coded | PSGR Type fixed by POSITION (Row1=CNN/Row2=UNN/Row3=INS/Row4=INF, confirmed -- not parsed from label text). MIN/MAX Age parsed from the sub-row LABEL. Percent/TicketDesignator/Accompanied parsed via regex from the condition text's LAST "FOR ... FARE TYPE:-" clause (confirmed heuristic when multiple clauses exist -- since there's no fare-context input to pick the "correct" one). `NoDiscount="YES"` when `Percent==100` is an unconfirmed single-example heuristic, always flagged when applied. **This logic was silently producing zero output on every real Type 1 file until bug #26's loader fix** -- the extraction rule itself was always correct, its input (the sub-rows) just never reached it |
| 20, 21, 22, 26, 27, 28, 29, 33 | Tour Conductor / Agent / Other Discounts / Groups / Tours / Visit Another Country / Deposits / Voluntary Refunds | Coded | `has_mapping=False` -- DataMapping explicitly says "no category-specific mapping defined" for every one of these. Template DOES have real category-specific columns for several (e.g. CAT20/21 mirror CAT19's Passenger Type/Age/PSGR Occur shape), but no data source exists to populate them |
| 23 | Miscellaneous Provisions | Coded | `has_mapping=False`. "Override Dates" explicitly marked CONSTANT "Not needed -- the format uses calendar dates". **Column layout quirk**: this category's block is shifted one position left vs every other category -- LOC1 is missing entirely (Zone1 sits first), AltGenTariff/AltGenRule/OW-RT are at O/P/M instead of the usual P/Q/N |
| 31 | Voluntary Changes | Coded | `has_mapping=False` for category-specific fields (pointer to unseen "FARE FAMILY FEE CONDITIONS" source, same pattern as CAT16). AltGenRule works automatically via the standard per-category IPRG mechanism (confirmed: Fare Rules "IPRG 0011" -> AltGenRule="0011"). DataMapping also describes a Type-2-only override pattern (same shape as CAT14's) -- out of scope for Type 1. **Has `ai_spec_file` configured (not yet active)** -- see note below on AI spec coverage |
| 24, 25, 30, 32 | -- | N/A | CAT24/30/32 don't exist in ATPCO's numbering (confirmed gap). CAT25 (Fare By Rule) exists in Fare Rules text but has **no corresponding block in the real template at all** -- not implemented, nowhere to write it |

**Type 1 scope is now feature-complete**: every category from CAT01 through CAT33 that has a real template block has a resolver, verified against a real XLSM file → real Excel template write, with all 29 category titles confirmed in order and no row collisions.

**AI spec coverage policy**: `ai_specs/catXX_spec.yaml` only exists for a category if either (a) it actually calls `_ai_extract_entry()` in its resolver, or (b) DataMapping does NOT explicitly say "no category-specific mapping defined" for it (i.e. there's real free text being ignored that could plausibly need AI later, like CAT16/CAT31's "FARE FAMILY FEE CONDITIONS" pointer). Categories where DataMapping explicitly confirms no mapping exists (CAT13, 18, 20-22, 23, 26-29, 33) deliberately have NO spec file -- there's no free text being discarded, so a spec would have nothing grounded to describe. This keeps specs meaningful (each one either active or a genuine "activate me later" placeholder) rather than mass-generating empty boilerplate for every category.

---

## 7. Bugs already found & fixed (don't reintroduce these)

1. **Wrong sheet targeted.** The template's `(FINAL TEMPLATE) CAT 1-CAT 33 w` sheet is **hidden**; Excel shows `(FINAL TEMPLATE) CAT 1-CAT 33 ` (no trailing "w") by default. `template_writer.py` now targets the visible sheet name, with a fallback, and force-sets `sheet_state="visible"`.

2. **`openpyxl.insert_rows()` silently drops cells** on this file (likely due to many merged cells / comments elsewhere in the sheet). Replaced with a manual `_shift_rows_down()` that unmerges/shifts/remerges explicitly, moving **both value and `._style`** together (an earlier attempt only moved values, leaving stale formatting -- a "misplaced banner" bug).

3. **`AltGenRule` (IPRG code) was category-blind.** `common_fields.py`'s `_extract_iprg_code()` used to grab the *first* IPRG value found across *any* category's Fare Rules row -- invisible bug because CAT01-04 all happened to share `"AB60"`. Broke the moment CAT08 (`"HK60"`) was added. Fixed by threading `category` through `extract_common_fields(anchor_row, pricebook_data, category)`.

4. **`has_mapping=False` returned zero rows, not one.** `entries=[]` meant a no-mapping category (CAT09) never got written at all. The template expects exactly one row per fare (its own placeholder rows prove this). Fixed to return `[self._blank_entry()]`.

5. **CAT050607's two-row header mis-detected.** The group row's merged cell ("ADV PURCHASE / MIN STAY / MAX STAY") contains all three keywords as substrings, tying with the true sub-header row's score in `find_header_row()`. Fixed tie-breaking to prefer the **later** row (`score >= best_score` instead of `>`).

6. **CAT050607's `UNIT` column repeats 3x** (once per ADV PURCHASE/MIN STAY/MAX STAY pair) -- a flat header can't disambiguate. `_read_cat050607()` pairs each `UNIT` positionally with the value column immediately to its left.

7. **Row-number source column varies.** Most category blocks number rows in column A, but CAT10's Qualifying Tables 106/107 number in column **P**. `_write_block()` now takes a `no_col` parameter (defaults to `"A"`).

8. **Used a post-shift row number as a "template constant".** When adding CAT09's `START_ROW`, a row number was copied from an *already-shifted* output file instead of the original blank template -- always read `START_ROW` constants from the untouched template, never from a filled/shifted copy.

9. **`data_mapping_parsed.json` has a recurring copy-paste pattern**: several categories' LOC1/Zone1/LOC2/Zone2/Fare Class/Family rows wrongly point to the `CAT 03-Seasonality` tab instead of their own category's tab (confirmed twice now -- CAT05 should read `CAT050607`, CAT11 should read `CAT11-Blackouts`, both confirmed by the user against real DataMapping text). **When a new category's parsed entry shows this exact tab reference, treat it as suspect and flag it for confirmation rather than trusting it verbatim.**

10. **Table-writing order must match the template's own top-to-bottom row order, not registry/dict order.** Qualifying Tables 106/107 sit physically BETWEEN CAT10 and CAT11 in the real template, but were being written AFTER CAT11-19 (since they were appended to `write_to_template()` after the main category loop). Once CAT11-19 started inserting their own rows, `cumulative_offset` included shifts from categories that come AFTER the qualifying tables in the file -- over-shifting their position into unrelated merged cells and crashing. Fixed by splitting category writing into ordered phases (CAT05-10 → Qualifying Tables 106/107 → CAT11-19) so every write happens in the same order as the physical file.

11. **CAT23's column layout is shifted one position left vs every other category** -- LOC1 is missing entirely from its Markets block (Zone1 sits where LOC1 normally would), and AltGenTariff/AltGenRule/OW-RT sit at O/P/M instead of the usual P/Q/N. Found only by directly inspecting the template row-by-row -- a reminder that column positions should never be assumed consistent across categories without checking.

12. **Data validations (dropdowns) and embedded images are anchored to fixed row positions and don't move with `_shift_rows_down()`.** The original template has 92 dropdown-list validations and 8 images, none of which our row-shifting logic touches (it only moves cell values and styles). Once enough categories needed more than the template's 3-row default capacity, dropdowns/images ended up sitting on whatever content happened to occupy their original row position -- visually scattered across unrelated rows. Fixed with `_strip_validations_and_images()`, called once at the start of `write_to_template()` before any shifting happens: clears `ws.data_validations.dataValidation` and `ws._images`. This is a deliberate tradeoff (the output file loses interactive dropdowns/decorative images) accepted because this is a generated filing-data file, not something a human fills in by hand.

13. **`dict(CATXX_COLS)` copy-paste without re-verifying the FULL column width.** CAT26-29 were assumed to share CAT20's column layout (which does have RI/Table/CAT at W/X/Y) via `CAT26_COLS = dict(CAT20_COLS)`, but an earlier verification pass only checked columns up to S (`range(1,20)`), never actually confirming W/X/Y existed for CAT26-29 specifically. They don't -- these four categories' blocks stop at column V (Sequence), no RI/Table/CAT at all. Caught only when the user visually inspected the actual file and asked "shouldn't this category only go up to column V?". **Lesson: when checking a category's column width, always scan a wide range (e.g. columns 1-45) rather than a range that happens to be "enough" for the categories checked so far -- and never assume two categories share a layout just because they're structurally similar (both "Passenger Type" categories, in this case) without directly confirming it.**

14. **`find_header_row()`'s scan window was capped at 20 rows.** Every real sample tested so far only had 1-2 rows of preamble before a table's real header, which isn't a representative stress test. A file with more extensive notes/legend text before the table (e.g. 30+ rows) would have silently picked the wrong row, since the real header was never scanned at all. Increased the default to 100 rows. Verified with a synthetic 35-row-preamble test (beyond the old cap) that the fix actually works, not just assumed. Residual risk, not fully eliminated: the scan window is now wide enough that a genuine DATA row could theoretically score a coincidental tie with the real header row on the same keywords, and the existing "prefer the later row on a tie" rule (needed for CAT050607's two-row header) would then pick the wrong one -- hasn't happened in any real file seen so far, but worth knowing about if a future file's data content coincidentally echoes its own header text.

15. **Real sheet names have formatting variance an exact match misses.** Confirmed on a real file where `"CAT03-Seasonality"` is actually named `"CAT03- Seasonality"` (one extra space). `_find_sheet(wb, expected_name)` added -- matches after stripping all spaces and lowercasing, so this kind of formatting-only difference doesn't hide a tab that's genuinely present.

16. **Category numbers come through inconsistently from real files.** Sometimes a string with stray whitespace (`"04 "`), sometimes a bare float (`10.0`, `11.0`, ...) since Excel auto-types a cell without a leading zero as a number instead of text. Every category resolver looks categories up by a zero-padded 2-digit string (`"04"`, `"10"`) -- without normalization this silently failed to match, hiding CAT04's (trailing space) and every CAT10+'s (float) actual condition text. Fixed with `_normalize_cat_number()`.

17. **Fare Rules' category-code column header varies.** Some real files merge it into a single `"RULE CATEGORIES"` header cell instead of separate `"RULE"`/`"CATEGORIES"` columns -- same data, different header text. Both spellings are now aliased to the same internal `"CAT"` key.

18. **IPRG header text can carry an annotation.** A real file had the header read `"IPRG\n[Check with FMU]"` instead of a bare `"IPRG"` (same column, extra text appended). `row.get("IPRG")` alone silently returned `None` on that file, dropping every `AltGenRule`. Fixed via `_get_iprg_value()` -- keyword-based (`key.strip().upper().startswith("IPRG")`), not exact match.

19. **`_shift_rows_down()` crashed on merged cells straddling the insertion point** (`AttributeError: 'MergedCell' object attribute 'value' is read-only`). Fixed to also unmerge (but deliberately NOT re-merge) any merged range where `r.min_row < insert_at <= r.max_row` before the shift happens.

20. **CAT03/04/05/06/07/11 all silently dropped `FareClassFamily` (and therefore per-row `OW/RT`) on every real file.** The real header text is `"FARE BASIS /\nFARE CLASS FAMILY"` (an embedded newline), but every resolver's lookup expected a plain space or no separator at all -- `.get()` on the wrong exact string just returns `None`, no error, no signal anything was wrong. Same root cause across all five categories, found once by diagnosing CAT03 in detail and then confirmed present verbatim in the other four via direct inspection. Fixed with a keyword-based `_lookup()` helper in each resolver (checks `all(kw in key.upper() for kw in keywords)` rather than exact-matching the whole header string). See section 13 for the related `OW/RT` mechanism this feeds into.

21. **CAT03's two-row header was mis-detected as the GROUP row, not the sub-header row** -- same two-row shape as CAT11-Blackouts/CAT050607 (`ORIGIN | DESTINATION | FARE BASIS... | SEASONALITY DATES` merged group row, with `SEASONALITY | PERIOD Start | PERIOD End` as the real sub-header one row below), but the generic `_sheet_to_rows()` reader picked the group row because its merged `"SEASONALITY DATES"` cell coincidentally contains the keyword `"SEASONALITY"` and out-scored the true sub-header row on the old flat keyword search. Effect: the sub-header row itself got read in as a bogus first DATA row, and `PERIOD Start`/`PERIOD End`/`SEASONALITY` never became real dict keys at all (they only exist on the row that was never selected) -- every CAT03 row's `FareClassFamily`/`FirstDate`/`LastDate`/`SeasonType` came out `None`, silently. Fixed with a dedicated `_read_cat03_seasonality()` two-row reader (same pattern as `_read_cat11_blackouts()`), located via keywords specific enough to only match the true sub-header row (`["PERIOD Start", "PERIOD End"]`, not the ambiguous `"SEASONALITY"`).

22. **CAT04's `Flight1` was hardcoded to `"GA"`.** Traced to this project's own synthetic test data, which happened to use Garuda Indonesia as its example carrier -- not a real constant. Confirmed via real files and explicit user confirmation: `Flight1` is always `"SQ"`.

23. **Real Type 3 file's `Fare Rule(POO)` sheet uses a different value-column label than Type 2's.** `_read_fare_rule_poo()`'s `find_header_row()` keyword list only recognized `"For Info Only"` (Type 2's POO label) -- Type 3's real POO sheet reuses the main sheet's single-column label, `"Same as Base Rule OR Amend Base Rule as indicated"`, instead. `value_col` silently stayed `None` for every category on a real Type 3 POO sheet, which routed every single category to AI unnecessarily (confirmed: reduced AI calls from 22 down to 8 on the same real file once fixed). Broadened the keyword list to accept both labels (plus `"IPRG Rule"`).

24. **Real Type 2 file's Fare Rules header had its own label shifted out of position.** The `"Rule Categories"` header cell sat one column to the RIGHT of where the category-code data (`"CAT 01"`, `"RBD"`, ...) actually starts, with no `"Category Description"` header at all -- every other column's header (Same as Base / override text / Alt Gen Rule) was correctly positioned, so a blanket column-shift would have broken those. Fixed narrowly: `_find_cat_code_column()` detects that ONE column by CONTENT (scanning sample rows for `"CAT NN"`/`"RBD"`-shaped values) instead of trusting the header row's own label position; the description column is then derived positionally (`cat_col + 1`).

25. **Output was formatted inconsistently -- mixed date shapes, mixed case -- because nothing ever normalized it.** `template_writer.py`'s single write chokepoint (`_write_block()`, `ws[...] = value`) wrote every value exactly as a resolver produced it. Two independent sources feed that chokepoint with no shared convention: deterministic values are copied verbatim from real pricebook cells (a date might be a real Excel date-typed cell in one file, free-typed text like `"01APR26"` in another -- no house style enforced across different filers/years), and AI-extracted values have no specified output format at all (`ai_specs/*.yaml` never told the model what date format or case to use, so it free-forms it per call -- confirmed live during this fix: the same run produced both `"01-OCT-17"` and ISO `"2017-10-01"` from two different AI calls in the same file). Every category resolver's `.upper()` calls only normalize case for their OWN internal matching/comparison, never what gets stored in `entry[field]` for writing. Fixed with `_normalize_output_value()` at the one chokepoint (not ~26 category files): the 10 confirmed date fields (`FirstDate`/`LastDate` CAT03, `Date1`/`Date2` CAT11, `OnAfterCommence`/`OnBeforeCommence` CAT14, `ReservationMustBeOnAfter/Before` + `TicketMustBeIssuedOnAfter/Before` CAT15) are parsed from a real `datetime`, `DD-MMM-YY(YY)` text, or ISO 8601 text, and written as real dates with `number_format="dd-mmm-yy"`; an unparseable date falls back to the original value (logged via `run_logger`, not silently dropped) rather than guessing. Every other string value is uppercased, except `PRICEBOOK NAME` (the uploaded file's own basename -- a traceability identifier back to the real source file, not a fare-filing code). Same root cause also explained a second, more serious issue: `run_new_filing.py`'s explicit `--rule-tariff` CLI path never uppercased RULE/TARIFF at all, while `intake_matcher.py`'s `--rule-tariff-text` path (the web form) only uppercased RULE, not TARIFF -- since `pipeline.py` groups/matches anchor rows by these exact strings, `"hkf1"` vs `"HKF1"` could have silently behaved as two different RULEs depending on which entry point was used, not just displayed differently. Both now uppercase RULE and TARIFF consistently.

26. **CAT10/15/16/19's Fare Rules sub-rows were silently invisible for Type 1 -- a deeper bug than it first looked.** Reported as "CAT10 comes back blank"; the real file's sub-row labels do have a leading `"> "` (e.g. `"> Circle Trips"`), which was a good lead, but wasn't the actual root cause. Confirmed by direct inspection of the real loader output: `_sheet_to_rows()` (the generic reader `load_pricebook_from_xlsm()` used for the "Fare Rules" sheet) has TWO compounding defects on this specific sheet -- (a) the sub-row label column has no header text of its own in the real file, so `_sheet_to_rows()`'s `{headers[i]: row[i] ... if headers[i] is not None}` comprehension drops that column's content entirely, and (b) there's no carry-forward of the category number: a category's own header row (e.g. `"10", "COMBINATIONS"`) is immediately followed by sub-rows that repeat no category number of their own, so every sub-row's `"CAT"` came out `None` -- meaning `_fare_rules.get("10", [])` returned only the single header row, and `get_fare_rules_subrows("10")` (which CAT10/15/16/19 all depend on) always came back empty, regardless of the `"> "` prefix. This was partially masked: CAT15's Location fields still worked because the AI call also reads the category's own flat condition text (which doesn't need sub-rows), so only its Ticketing Mode/Ticket Stock fields were silently missing; CAT16 currently has no confirmed extraction rule for its sub-rows anyway so the bug was dormant there; but **CAT19 (Children/Infant Discounts) came back completely empty** -- all 9 fields `null` across all 4 rows -- despite its positional extraction logic (`Row1=CNN/Row2=UNN/Row3=INS/Row4=INF`) being fully designed and already confirmed correct. Fixed with a new dedicated `_read_fare_rules_with_subrows()` (xlsm_loader.py), replacing the generic `_sheet_to_rows()` call for this one sheet -- locates the sub-row label column by CONTENT (scans for `"> "`-prefixed cells, same principle as bug #24's `_find_cat_code_column()`, since there's no header to trust), carries the most-recently-seen category number forward onto any row whose own CAT-number cell is blank, and strips the leading `"> "` before exposing the label as `SUB_ROW`. Verified end-to-end against a real file, not just the loader in isolation: CAT10 now resolves `CircleTripPermitted`/`EndOnEndPermitted`/`SingleOpenJaw`/`DoubleOpenJaw`/`SideTripsPermitted` with real values (and table 103's mirrored cell, bug #25's fix, now has real data to mirror instead of `None`-to-`None`); CAT15 additionally picks up `TicketingElectronic` from the previously-invisible Ticketing Mode sub-row; CAT19 now produces all 4 real rows (CNN 2-11 75% CH25, UNN 5-11 100% CH+NoDiscount, INS 0-1 75% IN25, INF 0-1 10% IN90) exactly matching the real source text; CAT16 unchanged (correctly still shows "no extraction rule defined" -- the sub-rows load fine now, there's just still nothing confirmed to extract from them).

27. **The template's own cover-page "CARRIER:" cell (F1) was hardcoded to `"GA"`.** Same root cause as bug #22 (CAT04's `Flight1` hardcoded to `"GA"`, traced to this project's original synthetic test data using Garuda Indonesia as its example carrier) -- except this instance lives directly in the template FILE itself (`template/SQ Fare Filling Template.xlsx`, cell F1, next to the `"CARRIER:"` label at E1), not in Python code. `template_writer.py` never reads or writes F1 (confirmed via `grep`) -- it was a static leftover in the raw template that every generated filing silently carried forward unchanged since the project began. Fixed by editing the template file directly (`ws["F1"] = "SQ"`, minimal load-modify-save, nothing else touched) rather than adding write-time code for it, since it's a constant cover-page label, not a per-row computed value. Verified: sheet dimensions, all 92 data validations, and all 8 images unchanged after the edit (matches bug #12's documented counts exactly); a real end-to-end run confirms a freshly generated filing now shows `F1="SQ"`.

28. **`intake_matcher.py`'s RULE detection could be tripped up by a broken formula's cached Excel error value.** Real user report, real file: a Type 3 sample (`..._CNF2(...)_DS Only.xlsm`) raised "found multiple DIFFERENT internal RULE values... `['#REF!', 'CNF2']`" -- 5 sheets correctly read `"CNF2"`, but `CAT04-FlightApplication`'s own "ATPCO Rule Number :" cell holds a broken cross-sheet formula whose cached value (under `data_only=True`) is the literal string `"#REF!"` (confirmed: the cell right below it, "Distribution :", is broken the same way -- a whole column of formulas in that one sheet references something that's since moved/been deleted). `_looks_like_rule_code()`'s old check (no spaces, 2-10 chars) happened to accept `"#REF!"` as a plausible candidate, so it was treated as a second, genuinely-disagreeing RULE value -- correctly triggering the "never guess between two real disagreements" safety check, just on a false disagreement: an Excel error token is never a legitimate RULE code under any circumstance, so it should never have become a candidate at all. Fixed by excluding every standard Excel error string (`#REF!`, `#DIV/0!`, `#N/A`, `#NAME?`, `#NULL!`, `#NUM!`, `#VALUE!`, `#GETTING_DATA`) from `_looks_like_rule_code()`, not just the one seen so far. Verified against the real failing file (now correctly detects `"CNF2"` with no error) and its sibling file from the same upload (`"CNF1"`, unaffected either way), plus isolated checks confirming each error string is rejected and real RULE codes still pass.

29. **A real submission got permanently stuck showing "matching files to fare rules" -- root cause was a catastrophic performance bug in `_sheet_to_rows()`, not a hang.** Real user report, real file: the run log showed matching had actually already SUCCEEDED (`"Matched files: ['HKF1']"` logged) with zero further progress for 4+ minutes afterward. The file's "Output" tab has `max_row=25000` (Excel reports this as the used range) while its real data ends at row 30 -- everything past that is phantom blank formatting, a very common real-world Excel quirk (dragged fill, formatting applied far beyond real data, etc.). `_sheet_to_rows()`'s old nested `ws.cell(row=, column=)` loop walked the FULL reported range regardless -- confirmed by direct timing: 5+ minutes and still not finished on this one sheet alone, vs. ~0.08s with the fix below. Because the single-worker queue (see webapp/jobs.py's own design note) processes one job at a time, this didn't just make one submission slow -- it silently blocked every other job behind it too. Fixed two ways in `_sheet_to_rows()`: (a) `ws.iter_rows(values_only=True)` instead of per-cell `ws.cell()` access -- meaningfully faster even without switching the whole workbook to `read_only=True` (which would need touching every other reader in this file that relies on style/merged-cell access `read_only` doesn't support); (b) stops after `MAX_CONSECUTIVE_BLANK_ROWS` (50) in a row, a real signal of having passed the true end of data rather than a rare gap inside it -- every real file's data seen so far is contiguous, so this bounds the read properly regardless of how large a sheet's phantom range is, on top of the raw speedup. Verified against the actual stuck file: full `load_pricebook_from_xlsm()` now completes in ~7s (was 5+ minutes, unfinished) and correctly reads all 29 real Output rows; regression-tested against HKF1/HKF2 (Type 1, unchanged row counts and CAT10 sub-row content) and a real Type 3 file's OW/RT sheet (262 rows, <1s) to confirm the two other callers of `_sheet_to_rows()` weren't affected. Also fixed a related but separate clarity gap while investigating: `webapp/jobs.py` kept the status label at `"matching"` through the ENTIRE file-loading phase that follows it too (not just the actual matching step), which would have read as misleading -- if not quite as severe -- even on a healthy run. Added a `"loading"` status between `"matching"` and `"resolving"` so progress is honestly reported; the frontend needed no changes, since `app.js` already displays whatever `status_label` the server sends generically.

30. **CAT08 had no NONE-phrase short-circuit at all, unlike CAT01/02/03/05/17 -- and this wasn't just a wasted-cost gap, it produced a genuinely misleading value.** Found while auditing why CAT08/CAT09 are the two "always AI" categories (neither has a REFER-TO-able tab in any real sample -- see section 3/6). Confirmed by directly testing CAT08's resolver with `"NONE UNLESS OTHERWISE SPECIFIED"` as input (the exact same phrase every other category recognizes as "no restriction"): the code had no check for it at all, so it fell straight through to `_ai_extract_entry()` -- a real AI call, ~38s, real tokens. Worse than the wasted cost: the real model **misread the standalone word "NONE" in that boilerplate phrase as answering the `MaxPermitted` field directly**, returning `MaxPermitted="NONE"` -- confidence=LOW but still a real, yellow-highlighted value in the output that reads as "stopovers not permitted," a specific business rule the source text never actually states. Fixed with the same `_is_none_condition()` check CAT01/02/03/05/17 already use (not a literal `== "NONE UNLESS OTHERWISE SPECIFIED"` string compare, so the CAT17-style "...DOES NOT APPLY" phrasing is caught too), placed before the REFER-TO branch. Verified three ways: the NONE-phrase case now short-circuits at 0.000s with `MaxPermitted=None`/confidence=HIGH (was 37.84s wall time, `MaxPermitted="NONE"`, confidence=LOW, before the fix); the real HKF1 file's genuinely non-empty CAT08 text (`"UNLIMITED FREE STOPOVERS PERMITTED..."`) still correctly reaches AI unchanged (`MaxPermitted="Unlimited"`, `Charge1NoCharge="YES"`, `ChargesApplyFor="Any Passenger"` -- matches the spec's own few-shot example); and a new `tests/test_cat08_stopovers.py` locks in both the NONE-phrase and CAT17-style-phrase short-circuits without needing a real AI call. CAT09 was checked too and already had this guard correctly in place (confirmed 0.000s, no AI call, on the same test input) -- no change needed there.

    **Follow-up sweep found two more instances of the same bug class.** Rather than assume CAT08 was the only one, every category in `pipeline.CATEGORY_REGISTRY` was systematically run with `"NONE UNLESS OTHERWISE SPECIFIED"` as input (AI mocked to keep the sweep fast/network-free -- only whether AI gets CALLED matters for this check, not what a real model would say). Found:
    - **CAT10** (`Side Trips`/`Notes` sub-rows): `if side_trips_text or notes_text:` -- a plain truthy check, no NONE-phrase exclusion. Confirmed live (mocked) that a `"Notes"` sub-row reading exactly that phrase still triggered a real AI call.
    - **CAT15** (main condition + `Ticketing Mode` sub-row): `if main_condition or ticketing_mode_text:` -- same shape.
    - **Confirmed clean**: every category with an explicit `NONE_UNLESS_SPECIFIED`/`_is_none_condition()` check (CAT01-08,11,12,14,17); CAT19, which already uses `needs_ai_fallback()` (also NONE_PHRASES-aware); every `has_mapping=False` category (structurally can't reach AI on Type 1 regardless of text); CAT16, which has no AI call anywhere in its Type 1 path yet.

    Fixed both CAT10 and CAT15 the same way -- `self._is_none_condition(text)` gating each field independently (so AI still fires if EITHER field has real content, only skips when BOTH are empty/none-phrase). Verified: the none-phrase-only case now short-circuits with confidence=HIGH and no AI call for both; a real HKF1 run confirms genuinely non-empty content on both categories still reaches AI completely unchanged (CAT10: `CircleTripPermitted`/`SideTripsPermitted`/etc. all resolve identically to before; CAT15: `Location1Value="HONGKONG"`, `TicketMustBeIssuedOnAfter`, etc. all unchanged). New `tests/test_cat10_cat15_none_phrase.py` locks in both fixes plus the "only skip when BOTH fields are none-phrase, not just one" boundary case, with AI mocked (not a real call) to keep the suite fast.

31. **CAT16 (Penalties) went from zero extraction to a real, grounded AI-based mapping** -- previously flagged as "Skeleton, almost nothing mapped" with no AI call anywhere in its Type 1 path at all. Investigated by pulling the real sub-row text directly (HKF1 and HKF2, identical on both): `"Voluntary Change/Refund/No show"` is confirmed to always be a bare pointer to an unseen external "FARE FAMILY FEE CONDITIONS" document (`"FARE FAMILY FEE CONDITIONS - CAT16"`, verbatim) -- never fed to AI, since there's nothing grounded to extract from it. `"Notes"` has real content (a flat per-ticket service fee description), but only grounds **7 of the real template's 34 category-specific columns** (`Z`-`BD`, confirmed by direct template inspection) -- the rest (`Before/After Departure`, the 3 Charge Type fields, all 6 Waivers fields, `Override Date`, etc.) are never mentioned in any real sample seen so far and are deliberately left unmapped rather than guessed, same principle as CAT05's unmapped ADV Res columns. New `ai_specs/cat16_notes_spec.yaml` (instruction + a few-shot example built from the real HKF1 text), `CAT16_COLS` in `template_columns.py` extended with the 7 grounded fields' real column letters, and `cat16_penalties.py`'s `_resolve_impl()` given real control flow (previously just returned a flagged blank entry unconditionally) -- including the same `_is_none_condition()` guard from bug #30/its follow-ups, so a `"Notes"` sub-row that happens to be empty or the standard no-restriction phrase doesn't trigger a wasted AI call.

    **A real near-miss caught mid-implementation, worth documenting so it doesn't happen again**: `cat16_penalties.py` already had `ai_spec_file = "cat16_spec.yaml"` set, reused by `_resolve_type2_3_embedded_iprg()` (the Type 2/3 mechanism built earlier this session, shared with CAT31) for a COMPLETELY different extraction -- pulling `AltGenRule` out of embedded "tag IPRG rule <code>" text. Writing this new Notes extraction straight into `cat16_spec.yaml` without reading the file first (it looked like a placeholder from the outside) would have silently overwritten that file's real content -- the Type 2/3 call would keep asking for `{"AltGenRule": null}` in its JSON schema (that part's built from the `output_fields` param, not the yaml) but with an *instruction* about charge fees and per-ticket amounts instead of IPRG codes, a genuine mismatch that would have quietly degraded real Type 2/3 output. Caught via `git status` showing the file as **modified**, not new, immediately after writing it -- restored the original via `git checkout`, then added a `spec_file` override parameter to `_ai_extract_entry()` (`base.py`) so a category can point different call sites at different yaml files without either one silently overwriting the other's meaning. `cat16_spec.yaml` (Type 2/3 AltGenRule) and `cat16_notes_spec.yaml` (Type 1 Notes) now coexist cleanly. Both re-verified independently after the fix: Type 1 HKF1/HKF2 (Notes extraction, confirmed twice -- one run hit a real JSON-parsing failure from the model, same known non-determinism class as CAT09's earlier retry, handled gracefully by the existing fallback; a second run came back clean) and Type 2 Cargolux 3J8F (embedded-IPRG, `AltGenRule="1HK7"`, matching the value this exact mechanism produced earlier in this same session, before any of this).

    Verified against both real files: HKF1 and HKF2 both correctly extract `ChargeAmt1=50`, `ChargeCur1="USD"`, `AppliesPer="Ticket"`/`"TICKET"`, all three `ChargeAppliesTo*` fields `"YES"`, and a cleaned `NoteText` -- matching the spec's own few-shot example closely. New `tests/test_cat16_penalties.py` covers the no-subrows/none-phrase/missing-Notes short-circuits (no AI call) and the real-content case (AI called, mocked, patched against `categories.base.extract_with_ai` since CAT16 goes through the shared `_ai_extract_entry()` helper rather than importing `extract_with_ai` directly) -- full suite: 50/50 passing in 0.5s.

---

## 8. Design decisions worth knowing

- **Output is organized per-category** (`{"CAT01": [...], "CAT02": [...]}`), matching the real template's separate per-category blocks -- NOT one merged wide row per fare. An early design sketch did this wrong; corrected before real coding started.
- **`data_mapping_final.json` (formerly `data_mapping_parsed.json`, removed during cleanup) is intentionally NOT wired into any code.** It's a parsed reference (all CAT01-33, Type 1/2/3 columns) from the user's `Final_Data_Mapping.xlsx`, used by hand when writing new `ai_specs/*.yaml` files or cross-checking a category's real column layout or Type 2/3 mapping. Keep it that way unless explicitly asked to change it.
- **Template capacity is dynamic, not fixed.** Every category block ships with only 3 example rows before the next category's header -- `_ensure_capacity()` shifts everything below down as needed, and `cumulative_offset` is threaded through `write_to_template()` so every subsequent category/table's position stays correct.
- **CAT04's Carrier Table No.1 linking**: the main row's own sequential position (its `No`) is copied into the supporting table's `CAT4 ID` column -- not a separate "Table 1" field (which turned out to be an unrelated CONSTANT pointer label, not a join key).
- **Sheet type (1/2/3) comes from the upload form** (or CLI flag), entered manually alongside RULE/TARIFF/file -- not detected from the file itself, and not cross-checked against it either (see section 15's known limitations). `GAP`-sourced fields only apply their mapping when `sheet_type == 1`.

## 9. Open items

- `ANTHROPIC_API_KEY` (the `AI_PROVIDER=anthropic` path) still has never been tested for real -- but AI extraction itself IS now verified end-to-end with real calls, via `AI_PROVIDER=openai_compatible` against a self-hosted model (see section 4). The mock path is what's now untested/unused in practice.
- The original synthetic test fixtures for Type 2/3 (`input_files_type2/`, `input_files_type3/`, and Type 1's `V1-ABC1 Type1.xlsm`) no longer exist on disk -- `test_from_real_files.py`/`test_type2.py`/`test_type3.py` currently fail with `FileNotFoundError`. See section 5 for detail. Not caused by this session's changes; not yet fixed either.
- CAT07's MIN STAY vs MAX STAY source column -- needs explicit user confirmation.
- CAT10: Record 3 Tables' `AJ`/`AL`/`AO` columns (Origin/Destination, OW-Fare-Allowed x2), Qualifying Tables 108/109, and whether Qualifying Table 107 should split into 2 rows (one per Open-Jaw sub-row clause) -- all still unconfirmed. (Table 103's `AN` column is now implemented -- see the CAT10 row in the category status table above.)
- Mixed per-field confidence (vs. current per-entry) would be needed if CAT04's Geographic Application block (documented as GAP-sourced from the same text as `Travel`, but with no field-level parsing rule) is ever implemented.
- `template_schema.py`'s `CATEGORY_HEADER_ROWS` is hardcoded per category, not auto-detected.
- `"OW"` (one-way only) has never actually appeared in any real Type 2/3 sample seen so far -- every row in every real file checked is `"RT/OW"`. The normalization mapping (section 13) is implemented and should handle it correctly if it does appear, but that specific branch is unconfirmed against real data.

## 10. Type 2/3 architecture (new, first pass)

Type 1's pricebook structure (`REFER TO`/`NONE UNLESS OTHERWISE SPECIFIED`
per category) does NOT apply to Type 2/3. Instead:

- **One shared mechanism across ALL categories**: every "Rule Categories"
  row has `Same as Base Reference Fare (Yes/No/NA)?`. `Yes`/`NA` → blank
  entry (follows Base Fare, nothing to extract). `No` → override text
  exists in `If "NO", amend Base Rule as follows:`, but no category has a
  confirmed extraction rule for it yet (CAT01/02/03 are the only ones
  analyzed so far, and DataMapping explicitly defers all three: "No
  request to code these yet").
- **`AltGenRule` source column differs per sheet type**: `IPRG` (Type 1),
  `For HO/TCS: Alt Gen Rule IPRG` (Type 2), `IPRG Rule` (Type 3) --
  unconfirmed whether Type 3 really differs this way or it's a doc typo
  (open item).
- **Preamble rows** (`RBD`, `CAT 50`) sit above `CAT 01` in the sheet --
  skipped by only keeping rows whose "Rule Categories" starts with `"CAT "`.
- **A second sheet, `Fare Rule(POO)`**, may exist -- detected by
  **keyword** (`"poo"` substring in the sheet name), not an exact name
  match, since naming varies (`"Fare Rule(POO)"` vs `"Fare Rules POO"`).
  Its value is currently always `"FOLLOW BASE FARE"` (copy whatever the
  main "Fare Rules" sheet resolved for that category) -- no other value
  has been seen yet, so that's the only branch implemented.

### New files
- `pricebook_data_type2.py` -- `PricebookDataType2`, much simpler shape
  than Type 1's (one row per category: `same_as_base`, `override_text`,
  `alt_gen_rule`).
- `xlsm_loader.py` additions: `load_pricebook_type2()`, returns
  `(main_pricebook, poo_pricebook)` -- `poo_pricebook` is `None` if no
  `"poo"`-named sheet exists.
- `categories/base.py`: `resolve()` now routes `sheet_type in (2, 3)`
  to a NEW generic `_resolve_type2_3()` BEFORE the `has_mapping` check --
  this method lives in the base class (not per-category) because the
  Yes/No/NA mechanism is identical everywhere. Sets `bundle["common_override"]`
  (dict of common-field values that take precedence over
  `common_fields.py`'s defaults) for the dynamic `SAME AS BASE REFERENCE
  FARE ?` value, Type-2/3-sourced AltGenRule, and (added later, see
  section 13) `OW/RT`. **6 categories DO override this method themselves**
  (CAT10, CAT14, CAT15, CAT16, CAT19, CAT31 -- see their own sections
  below) and each needed the same `OW/RT` addition made to their own
  `common_override` dict independently.
- `pipeline.py`: `run_pipeline()` now merges `bundle.get("common_override",
  {})` into every row (no-op for Type 1, which never sets it). New
  `run_pipeline_type2_3()` resolves the main sheet via the normal
  `run_pipeline()`, then separately walks `Fare Rule(POO)`, copying the
  matching main-sheet row through when POO value is `"FOLLOW BASE FARE"`.
- `template_writer.py`: core writing logic extracted into
  `_write_pipeline_output_to_sheet(ws, pipeline_output, anchor_rows)` so
  it can run against two different worksheets. New
  `write_to_template_type2()` duplicates the main sheet via
  `wb.copy_worksheet()` (renamed `"CAT 1-CAT 33 (POO)"`, kept ≤31 chars --
  Excel's sheet-name limit) and writes `output_poo` into the copy.
- `common_fields.py`: `_extract_iprg_code()` now checks
  `hasattr(pricebook_data, "get_fare_rules_row")` before calling it --
  `PricebookDataType2` doesn't have this method (Type 2/3's AltGenRule
  comes entirely through `common_override` instead), so this just
  returns `None` gracefully rather than crashing.
- `input_files_type2/build_pricebooks_type2.py` + two generated skeleton
  files (`V1-ABC1-Type2.xlsm` RULE=2KLM, `V2-ABC2-Type2.xlsm` RULE=3MNO
  with 2 TARIFFs) -- CAT01/02/03/14/CAT50/RBD have real example content
  from chat; CAT04-19 are placeholder "Yes" rows for realistic file shape.
- `test_type2.py` -- end-to-end test, verified: all confirmed categories
  correctly resolve `SAME AS BASE REFERENCE FARE ?` dynamically from the
  Yes/No/NA column (not hardcoded "NA" like Type 1), and the POO sheet
  correctly mirrors the main sheet's resolved values.

### Open items (Type 2/3)
- **CAT15-19, 26/28/29, CAT31 now fully implemented** for Type 2/3, all confirmed from real samples in one batch:
  - CAT15: regex extracts `TicketMustBeIssuedOnAfter` from "FOR SALES ON/AFTER <date>"; the rest (ticket stock/ticketing mode/notes) routes through the same AI mechanism as Type 1.
  - CAT16 & CAT31: **confirmed to be separate real rows** (resolved the earlier "shared row" ambiguity -- both categories' Type 2 "Category Description" just happens to read "Penalties / Rebooking" coincidentally). `AltGenRule` is embedded IN the override text ("...tag IPRG rule <code>"), extracted via regex, since the separate IPRG column is blank for these two.
  - CAT19: `resolve_poo_single()` hook added to `base.py` -- lets a category handle a non-"FOLLOW..." POO value directly (maps to `NoDiscount`) instead of falling through to blind AI. Confirmed working with real POO text that differs from the main sheet's text.
  - `base.py`'s Yes/No/NA check now also recognizes `"NOT APPLICABLE"` as equivalent to `"NA"` (confirmed from CAT26/28/29's real sample -- previously only exact `"NA"` matched).
- **CAT25 ("Ticketing Code") -- confirmed to exist in Type 2 Fare Rules, but NOT implemented.** Real sample: `CAT 25 | Ticketing Code | All ODs | No | Code per "Corporate ID" above`. No corresponding block exists anywhere in the real Type 1 template (confirmed earlier in this project) -- there's nowhere to write this even if resolved. Flagged for the user, not silently skipped or invented.
- CAT12/13/17/18's `OW/RT` is "No request to code these yet" for Type 2 (vs. CAT03/10/11/14/15/19 which have the Edifact/NDC mechanism) -- confirms this is genuinely per-category, not universal (see note above about not generalizing it into base.py). This is now moot for the generic path anyway -- `_lookup_owrt_type23()` (section 13) resolves project-wide for EVERY Type 2/3 category regardless of whether DataMapping calls it out per-category, since there's no per-category Fare Class context to narrow it further either way.
- Whether Type 3's `IPRG Rule` column is real or a documentation typo -- still no Type 3 sample data existed at the time this was written. (Real Type 3 samples are now in regular use -- see section 13 -- but this specific column hasn't been re-checked against them.)
- CAT04-09 not analyzed for Type 2/3 at all yet.
- **New master reference**: `data_mapping_final.json`, parsed from user-uploaded `Final_Data_Mapping.xlsx` -- has ALL categories (CAT01-33) with Type1/2/3 columns cleanly separated. Check this FIRST before asking the user for a category's Type 2/3 mapping again.

### CAT10 Type 2/3 -- fully implemented, the first real example of a
### category needing its own Type 2/3 override

Confirmed from real data: CAT10 has its OWN sub-row structure in Type 2
(Circle Trips / Side Trips / End-on-End / Half Round Trip..., matching
Type 1's shape) -- `Cat10Resolver._resolve_type2_3()` overrides the
generic base.py fallback, reusing the EXACT SAME regex logic as Type 1
(`_open_jaw_value()`, `_table107()` unchanged), just reading
`override_text` from Type 2 sub-rows instead of `FARE RULE CONDITIONS`.
Sub-row labels are matched case-insensitively (`_get_subrow_ci()`) since
Type 2's real sample capitalizes differently ("End-on-End combination"
vs Type 1's "End-on-End Combination").

**Confirmed and important**: `Fare Rule(POO)` for CAT10 is NOT
`"FOLLOW BASE FARE"` -- it has its own sub-rows too, with the Open-Jaw
clause's text genuinely differing (POO drops "AND RULE <WC21/.../WC29>",
main sheet keeps it). Per project decision, `run_pipeline_type2_3()`
routes any multi-row POO category straight to AI (`_ai_fallback_entry()`,
using the resolver's own `ai_spec_file`/`output_fields`) rather than
guessing a copy-through rule -- verified end-to-end
(`source_branch="POO_AI_EXTRACTED"`).

Also fixed while building this: `_table107()`'s regex only captured the
FIRST token after "THIS RULE AND RULE" (e.g. just `<WC21/`) -- now
captures the full bracketed list up to "IN ANY TARIFF".

## 11. Type 3 architecture

Confirmed via real screenshots + full CAT01-33 sample (files: `V1-DEF1-Type3.xlsm`,
`V1-DEF2-Type3.xlsm`): structurally similar to Type 2 but with ONE KEY
DIFFERENCE -- the main sheet has a SINGLE combined column ("Same as Base
Rule OR Amend Base Rule as indicated") instead of Type 2's two separate
columns (Yes/No/NA flag + override text). The POO sheet's structure is
IDENTICAL to Type 2's POO sheet.

**Implementation approach**: rather than rewriting every category's
`_resolve_type2_3()` for a third time, `xlsm_loader._synthesize_same_as_base()`
converts Type 3's single column into the SAME `{same_as_base, override_text}`
shape Type 2 produces (`"FOLLOW ..."` or `"NOT APPLICABLE"`/`"NA"` → synthetic
`"Yes"`, no override; anything else → synthetic `"No"`, override_text = the
column's content verbatim). `load_pricebook_type3()` returns the same
`PricebookDataType2` class Type 2 uses -- **zero changes needed to any
category resolver** to support Type 3. Verified end-to-end: CAT10, 14, 15,
16, 19 (main and POO) all produced correct results using their existing
Type 2 code, unmodified.

Two minor real-data-driven tweaks made along the way (not Type-3-specific,
just caught while testing with Type 3 samples):
- CAT10's Notes sub-row lookup now also accepts the label "Other" (not just
  "Notes"/"Other (notes)") -- Type 3's real sample uses this bare form.
- CAT15's date regex broadened from requiring "SALES ON/AFTER" to matching
  any "ON/AFTER <date>" -- Type 3's real sample phrases it "TICKETS MUST BE
  ISSUED ON/AFTER <date>" instead.

Sheet name detection reused the existing keyword logic (`"fare rule"`
substring, excluding `"poo"`) without any changes -- correctly identified
`"CORP_FARE RULES(CN)"` and `"CORP_FARE RULES-POO"` despite completely
different naming from Type 2's `"Fare Rules"`/`"Fare Rule(POO)"`.

### Open items (Type 3)
- CAT04-09 still not analyzed in detail for Type 2/3 (both types) --
  current real samples for these all happen to be "FOLLOW BASE FARE"/"Yes",
  so the generic SAME_AS_BASE path is exercised but no override text case
  has been seen yet.
- ~~OW/RT's Edifact/NDC normalization table is still missing for both Type
  2 and Type 3~~ -- **implemented and verified**, see section 13.

## 12. Granular AI fallback + Excel highlight (new)

**Trigger rule** (`categories/base.py`, `needs_ai_fallback(text, extracted_value)`):
text has real content AND isn't a known no-op phrase (`NONE_PHRASES` or
`"FOLLOW ..."` prefix) AND the deterministic regex/logic came back `None`
-> try AI as a second attempt before leaving the field blank.

**Where this is wired in** (all confirmed working via real test cases,
not just written -- see CLAUDE.md bug list update below):
- `CAT14` (Type 2/3 only -- Type 1's fields stay permanently deferred by
  design, untouched): `OnAfterCommence`/`OnBeforeCommence`.
- `CAT15` (Type 2/3): `TicketMustBeIssuedOnAfter` is folded into the
  SAME AI call CAT15 already makes for Location/Ticketing fields --
  no extra API call, just one more field in the schema.
- `CAT16` / `CAT31` (Type 2/3): `AltGenRule`, when the embedded "IPRG
  rule <code>" regex fails on real text.
- `CAT19` (Type 1): `Percent`/`TicketDesignator`/`AccompaniedTravel`/
  `SameCMPT`/`AccompanyingMinAge`, via a TARGETED AI call (only those 5
  fields, not the full 9-field output_fields list -- PSGRType/MinAge/
  MaxAge/NoDiscount aren't derivable from an isolated clause snippet).
- `CAT10`: deliberately UNCHANGED -- Circle Trip/End-on-End stay a raw
  copy (no validation), and the Open-Jaw "Restricted" default stays a
  confirmed rule, not a failure case, per explicit user decision.

**`ai_used` flag**: set at the single choke point (`ai_engine.py`'s
`extract_with_ai()`, both the mock-response and real-response paths) --
every direct or indirect AI call inherits it automatically. For the
handful of call sites that manually copy specific fields out of an
`ai_result` dict instead of using the whole thing (CAT10, CAT15, CAT16,
CAT31, CAT19), `entry["ai_used"] = ai_result.get("ai_used", False)` is
set explicitly alongside those copies.

**Excel highlight is now per-CELL, not per-row** (changed from the
original per-row design, per explicit later user request -- "highlight
the cell instead of the whole row"). The original per-row version
applied `AI_USED_FILL` across the FULL WIDTH of any row where
`row.get("ai_used")` was true -- simple, but meant common fields
(PRICEBOOK NAME/RULE/TARIFF/AltGenTariff/AltGenRule/OW-RT, which are
NEVER AI-derived, in any category) got shaded too, purely for sharing a
row with a genuinely AI-derived field, and a category with only 2 of 9
fields AI-touched still had the other 7 shaded regardless.

Mechanism: `ai_engine.py`'s `extract_with_ai()` now also returns
`ai_fields` -- the subset of `output_fields` the AI actually populated
(non-None), computed once at the single choke point. For a category that
does WHOLE-entry extraction (`entry = self._ai_extract_entry(...)`, no
selective harvesting -- most categories: CAT01-09, CAT11, CAT12, CAT17,
and CAT10's POO fallback via `pipeline.py`'s `_ai_fallback_entry()`) this
is already correct with zero extra work, since every field the AI
returned non-None IS what the resolver keeps. For the categories that
harvest only SOME AI-returned fields into a pre-existing entry with an
`entry[f] = entry[f] or ai_result.get(f)` pattern (CAT10's Side Trips/
Notes, CAT14, CAT15 x2 call sites, CAT16, CAT19, CAT31 -- 8 call sites
total), `categories/base.py`'s new `_copy_ai_fields(entry, ai_result,
field_names)` helper does the copy AND tracks, field-by-field, whether
the FINAL value in `entry[f]` actually came from AI (empty before AND
AI provided one) vs. was already deterministic (regex/lookup value
wins, never overwritten, never marked) -- exactly preserving each site's
original "regex wins over AI" semantics, just also tracking it. Union
across multiple AI calls on the same entry, not overwrite (CAT15 makes
two separate calls that can both contribute). CAT16/CAT31's `AltGenRule`
is a special case -- it's a local variable threaded through
`bundle["common_override"]`, never a key of `entry` itself, so those two
sites mark `entry.setdefault("ai_fields", set()).add("AltGenRule")`
directly instead of going through the helper.

`template_writer.py`'s `_write_block()` then checks `field in
row.get("ai_fields", ...)` per cell instead of blanket-filling all 90
columns per row. Verified end-to-end against real files, not just unit
tests: a real Type 1 run confirmed CAT08 (whole-entry) shaded only its 3
AI-derived fields with common fields clean, and CAT15 (targeted) shaded
only its 4 AI-derived Location fields; a real Type 3 run additionally
confirmed the CAT10 POO-vs-main-sheet distinction holds exactly as
documented above -- the SAME field names (CircleTripPermitted et al.)
are correctly shaded on the POO sheet (legitimately whole-entry
AI-derived there) and correctly NOT shaded on the main sheet (CAT10's
main-sheet resolution is deliberately never AI-touched, unchanged from
before). **Color stays bright yellow (`FFFF00`)**, only the highlighted
area changed.

**Fixed along the way**: CAT02 had a field-name bug -- output_fields had
a single `"DayOfWeek"` key, but `template_writer.py`'s `CAT02_COLS` (correct)
expects 7 separate keys (`Mon`..`Sun`) matching the template's 7 separate
columns (AD-AJ). The mismatch meant those columns were ALWAYS blank
regardless of extraction quality, since the field names never matched.
Fixed by splitting into 7 fields. Also removed a dead `"OWRT"` field from
both CAT02 and CAT03 (the real common field is `"OW/RT"` with a slash,
handled separately by `common_fields.py` -- `"OWRT"` without a slash
never matched anything in `COLS` and was never written anywhere).

Also discovered: the real template's day-of-week header row literally
reads "M","T","W","T","F","S","S" (Tue/Thu both "T", Sat/Sun both "S") --
ambiguous as AI prompt labels on their own. `_ai_extract_entry()` gained
an optional `label_override` parameter; CAT02 passes
`DAY_LABEL_OVERRIDE` (`{"Mon": "Monday (M)", ...}`) to disambiguate.

## 13. OW/RT mechanism (Type 1 and Type 2/3)

`OW/RT` is a common field (written on every category's output row,
alongside `PRICEBOOK NAME`/`RULE`/`TARIFF`/`AltGenTariff`/`AltGenRule`),
but unlike those, its real value depends on the airline's per-Fare-Class
data, which lives on a COMPLETELY DIFFERENT sheet/value-domain depending
on sheet type. Confirmed this session, both directions, against real
files.

### Type 1 -- `common_fields.py`'s `_lookup_owrt()`

Source: the pricebook's `"Output"` tab, one row per Fare Class (NOT one
row per RULE -- confirmed on a real file where the same RULE had both
`OW/RT=2` and `OW/RT=3` across different Fare Class rows). Values are
numeric codes: `1=OW only, 2=RT, 3=OW/RT (both)` (`OWRT_CODE_MAP`).

- **Generic fallback** (`extract_common_fields()`'s default for every
  category): only resolves to something if EVERY row in the Output tab
  agrees on the same code -- otherwise returns `None` rather than
  guessing. This is the only option for categories with no Fare Class
  context of their own.
- **Per-row override** (categories with their OWN Fare Class per row --
  CAT03, CAT04, CAT05, CAT06, CAT07, CAT11, confirmed so far): each
  resolver calls `_lookup_owrt(pricebook_data, entry["FareClassFamily"])`
  and overwrites the generic default for that specific row. `fare_class_text`
  can combine multiple codes (`"VT6HKR / KT6HKR"`, `"V/K"`) -- matches
  against ANY of them, via prefix (`.startswith()`, after stripping a
  trailing `"-"`) since a resolver's `FareClassFamily` is often a prefix
  (`"KV6-"`) while the Output tab stores full codes (`"KV6HKR"`). Still
  returns `None` (not a guess) if the matched rows disagree on the code,
  or if `FareClassFamily` is itself `"ALL"`/`"ALL FARE CLASSES"` and the
  whole Output tab disagrees.
- Every per-row override lives in that category's own `_map_row()`/
  `_resolve_impl()` -- see the category status table above for which of
  CAT03/04/05/06/07/11 fixed this. CAT12 (Surcharges) would need it too
  but has no `CAT12-Surcharges` tab reader yet (skeleton only).

### Type 2/3 -- `common_fields.py`'s `_lookup_owrt_type23()`

**Completely different source and value domain from Type 1** -- this was
the single biggest gap closed this session, previously undocumented and
unimplemented (the "Output" tab doesn't exist on Type 2/3 files at all).

Source: a separate real per-fare-class data sheet -- NOT `"Fare Rules"`/
`"...POO"`, and NOT named consistently across real files
(`"Edifact_Filing_CDM_A7J8F"`, `"NDC_Filing_CDM_A7J8F"`, `"Faresheet "`,
confirmed on 4 different real samples). Located by CONTENT, not name:
`xlsm_loader._find_owrt_sheet()` scans every sheet for a literal
`"RT/OW"` header cell (has always been sheet index 0 on every real sample
so far, but located by content anyway rather than trusting that). Values
are TEXT, not numeric: `"RT/OW"` (both directions permitted) or `"OW"`
(one-way only) -- `OWRT_TEXT_MAP`. Only `"RT/OW"` has been seen in real
data so far (see section 9's open items).

No per-category Fare Class context exists for the generic Type 2/3
branch (unlike Type 1's CAT03/04/05/06/07/11) -- `_lookup_owrt_type23()`
only resolves project-wide, same "only if every row agrees" conservatism
as Type 1's generic fallback.

**Wired in TWO places**, both needed:
- `categories/base.py`'s generic `_resolve_type2_3()` -- covers every
  category that doesn't override it.
- The 6 categories that DO override `_resolve_type2_3()` themselves
  (CAT10, CAT14, CAT15, CAT16, CAT19, CAT31) each needed their own
  `common_override` dict updated too -- fixing only `base.py` would have
  silently left these 6 categories still missing `OW/RT`, since they
  never fall through to the generic method at all.

New/changed files: `xlsm_loader.py` (`_find_owrt_sheet()`,
`_read_owrt_rows()`, wired into both `load_pricebook_type2()` and
`load_pricebook_type3()`), `pricebook_data_type2.py` (`PricebookDataType2`
now carries `owrt_rows`), `common_fields.py` (`_lookup_owrt_type23()`,
`OWRT_TEXT_MAP`).

Verified end-to-end against real files, both Type 2 (Cargolux CDM/NDC)
and Type 3 (Tianqi): every category correctly resolves `OW/RT = "OW/RT"`
(matches the real data, where every row is literally `"RT/OW"`). A
category correctly stays `None` only when its own Fare Rules row wasn't
found in that specific file at all (an unrelated, pre-existing branch,
not an OW/RT bug).

## 14. How to run (CLI)

The real upload form now exists (`webapp/`, see section 15) and is the
primary way to run a new batch of files. This CLI entry point still has
its place -- explicit `--file`/`--rule-tariff` pairing is convenient for
scripted or one-off runs against files whose RULE you already know,
without going through a browser.

```bash
cd fare_filling_poc
.venv\Scripts\python.exe run_new_filing.py --sheet-type 1 --wo-id 4002 \
    --file "..\input_files\HKF1.xlsm" --rule-tariff "HKF1(FBRA3P)" \
    --file "..\input_files\HKF2.xlsm" --rule-tariff "HKF2(FBRA3P,FBRINPV)"
```

`run_new_filing.py` flags: `--sheet-type` (1/2/3, applies to every `--file`
in the run -- run again separately for a different type), `--wo-id`
(written to the output template's cover cell), `--file` (repeatable, one
pricebook per flag), `--rule-tariff` (repeatable, `"RULE(TARIFF1,TARIFF2)"`,
paired in order with `--file`), `--output` (optional, defaults to
`SQ Fare Filing_<WO_ID>_Type<N>.xlsx` next to the script).

Produces, per run: the filled Excel template; `pipeline_output_new_filing.json`
(pure filing data); and a timestamped run log,
`run_log_<WO_ID>_Type<N>_<ddmmyyyy_hhmmss>.txt` -- progress, every AI call
(provider/model/timing/token usage), and an end-of-run summary (total
time, AI call counts, token totals) via `run_logger.py`. The log is kept
deliberately separate from the JSON/xlsx outputs -- it never touches
filing data, it's diagnostics only.

Before running, `ai_config.env` (see section 4) needs `AI_PROVIDER`,
`AI_BASE_URL`/`AI_MODEL` (or `ANTHROPIC_API_KEY` for the other provider)
set -- without it, every AI call falls back to a clearly-labeled mock.

The older regression scripts (`test_from_real_files.py`, `test_type2.py`,
`test_type3.py`) are currently broken -- see section 5/9, their fixture
files no longer exist. `run_new_filing.py` against real files in
`input_files/` is the verified way to exercise the pipeline right now.

## 15. Web upload form (`webapp/`)

Lives at the project root, sibling to `fare_filling_poc/`, not inside it
(`webapp/` imports from `fare_filling_poc/` via `sys.path.insert`, same
pattern `run_new_filing.py` already used). Wraps the exact same pipeline
functions the CLI calls -- `run_pipeline()`, `run_pipeline_type2_3()`,
`write_to_template()`, `write_to_template_type2()` -- behind a small
FastAPI service. No pipeline logic is duplicated for the web layer.

**Verified end-to-end, through the real HTTP form (not just curl or the
CLI), for all three sheet types against real production files** -- HKF1/
HKF2 (Type 1), Cargolux CDM (Type 2, RULE `3J8F` correctly auto-detected
from content), Tianqi Edifact (Type 3, RULE `3RY4`).

### Files

```
webapp/
|-- server.py          # FastAPI routes: GET / (the form), POST /api/jobs,
|                       # GET /api/jobs/{id} (status), GET /api/jobs/{id}/download,
|                       # GET /api/health. Validates wo_id (path-safe regex),
|                       # sheet_type, and file extensions BEFORE a job is created.
|-- jobs.py              # Single background worker thread + FIFO queue. Wraps
|                       # intake_matcher.match_files_to_rules() -> load_pricebook_*()
|                       # -> run_pipeline*() -> write_to_template*(), reporting
|                       # progress into an in-memory job dict instead of stdout.
|-- static/
|   |-- index.html       # The form -- built to match a real reference screenshot
|   |-- style.css         # (pale-cyan/navy palette, "ati Business Group" branding)
|   `-- app.js            # Client-side validation, drag/drop, status polling,
|                       # auto-download on completion
|-- uploads/              # Per-job: uploaded files + run_log.txt (gitignored)
`-- outputs/               # Completed .xlsx per job (gitignored)
```

### Why single-worker, not concurrent

`run_logger.py` is module-level global state (`set_log_file`/`log`/
`record_ai_call` all write shared module variables) -- two concurrent
pipeline runs in different threads would interleave and corrupt each
other's progress log. A FIFO queue (one `threading.Thread` worker,
`queue.Queue` of job IDs) is the simplest correct fix. At expected usage
volume (tens of WOs/month, per the ROI numbers worked out earlier this
project), jobs briefly queueing behind each other is not a real
bottleneck -- revisit only if usage grows enough to make it one.

### Job status lifecycle

`queued -> matching -> loading -> resolving -> writing -> done` (or
`error` from any stage). `matching` = `intake_matcher.match_files_to_rules()`;
`loading` = reading each matched file's pricebook data (`xlsm_loader.py`
-- added as its own status after a real stuck job revealed this used to
run silently under the `matching` label, see bug #29); `resolving` =
category resolution; `writing` = `template_writer`. The browser polls
`GET /api/jobs/{id}` every 2s and auto-triggers the download once
`status == "done"` (`window.location.href` to a `Content-Disposition:
attachment` response -- this does NOT navigate the page away, confirmed).

### Validation & guardrails (all confirmed by deliberately triggering them, not just written)

- **Path-traversal guard**: `wo_id` is validated server-side against
  `^[A-Za-z0-9_-]{1,64}$` before use. It's embedded directly into the
  output filename (`SQ Fare Filing_<wo_id>_Type<N>_<job_id>.xlsx`) --
  without this check, a `wo_id` of `../../evil` could have influenced
  where the completed filing gets written. Confirmed blocked with a real
  request.
- **File-extension guard, both layers**: client-side (`app.js`, inline
  warning, file dropped before upload) AND server-side (`server.py`,
  hard 400) both reject non-`.xlsm`/`.xlsx` uploads. The client check
  alone is trivially bypassable (curl, or a modified request) -- the
  server check is the one that actually matters. Confirmed both reject a
  `.txt` file.
- **RULE matching is content-based** -- see `intake_matcher.py`'s own
  docstring for why filename matching (fails on Cargolux: RULE `3J8F`
  isn't a substring of filename `A7J8F`) and upload-order matching
  (silent, unrecoverable mismatch risk) were both ruled out. Any
  mismatch, duplicate, or unmatched RULE/spec is a hard, specific error
  -- never a guess.
- **Mismatched Filing Classification Type fails safely, not silently.**
  Deliberately tested: submitting a real Type 2 file with "Type 1"
  selected does NOT produce a corrupted/garbage filing -- Type 1's
  loader expects a sheet literally named `"Fare Rules"` that the Type 2
  file doesn't have under that name, so it raises `KeyError` before any
  output is written. The raw exception is logged in full server-side
  (`run_logger.log()` + `traceback.print_exc()`) for real debugging, but
  the user sees a plain, actionable message instead: *"This filing could
  not be processed. The most common cause is the uploaded file not
  matching the selected Filing Classification Type..."* (`jobs.py`'s
  outer `except Exception` handler). **Known gap, not yet fixed**: there
  is no proactive check *before* Submit that catches this -- it only
  surfaces after processing starts.

### A real regression, found by actually driving the form (not by reasoning about the code)

The hidden file `<input type="file" ... hidden>` kept its HTML
`required` attribute. Browsers cannot show the native "please fill this
out" validation bubble on a hidden field, so an incomplete form's submit
was silently cancelled entirely -- console showed `An invalid form
control with name='files' is not focusable`, zero requests ever left the
browser, nothing visible happened. A first attempted fix (removing the
Submit button's own `disabled` gating) was necessary but not sufficient
-- it never got a chance to run, since the browser blocked the submit
one step earlier. Real fix: removed `required` from the file input, and
added `novalidate` to the `<form>` so ALL validation now runs through
`app.js`'s `validateForm()`, which always shows exactly what's missing.
Confirmed via a real headless-browser session (Playwright), not just
inspection. Now covered by `ci/browser_smoke_test.py` (section 16) so
this exact class of bug can't silently return.

### Known limitations (accepted for this version, not oversights)

- **No upload/output retention policy yet.** `webapp/uploads/` and
  `webapp/outputs/` grow with every submission, forever. Needs a cleanup
  job before running unattended for real -- see
  `docs/deployment-runbook.md` section 7.
- **No authentication.** Deliberate choice for this internal-only
  version (per explicit decision when the form was scoped). Revisit if
  usage moves beyond a small trusted group.

**Submissions are now rate-limited per IP** (`webapp/ratelimit.py`, new
-- `POST /api/jobs` only; `GET /api/jobs/{id}` is deliberately NOT
throttled, since the frontend legitimately polls that every 2s per
active job). With no authentication still in place, this was the one
thing standing between an accidental (a stuck retry loop) or deliberate
burst of submissions and it monopolizing the single-worker queue for
everyone else -- the queue's single-worker design (see webapp/jobs.py)
means one client's burst doesn't just cost that client time, it pushes
every other real submission behind all of it, for as long as each of
those jobs takes to run (minutes, not milliseconds). Plain in-memory
sliding window, not a library -- 5 submissions per 10-minute window per
IP, generous headroom above real usage (~35 WOs/month overall, roughly
1-2/day) while still bounding a runaway client to a small head start
rather than an unbounded one. Deliberately not persisted -- pacing
within one running process's lifetime, not something that needs to
survive a restart. Verified two ways: a direct unit test of the exact
boundary (5 allowed, 6th+ blocked, a different IP unaffected), and a
real end-to-end test through the live server -- 6 rapid submissions,
the first 5 returned real job ids (HTTP 200), the 6th was rejected with
HTTP 429 and a clear "please wait ~10 minutes" message.

**A submission is now recorded in an audit trail** (`webapp/audit.py`,
`webapp/audit.log`, gitignored -- real submission data, same reasoning
as `webapp/uploads/`/`outputs/`). One append-only line per accepted
submission: timestamp, job id, WO ID, sheet type, requesting IP, and
filenames -- written the moment a job is accepted, before the worker
picks it up, so the record exists even if the job later fails or the
server restarts mid-run. Deliberately a plain text file, not a database
or structured logging -- matches `run_logger.py`'s existing style rather
than adding a dependency for a currently low-volume tool. This doesn't
answer "who" beyond an IP address, since there's still no authentication
(see the item above) -- it closes the "we have no record of any of
this" gap, not the identity gap.

**A queued job now shows its real position in line**, not just
"Queued" with no context. `webapp/jobs.py` tracks `_queue_order` (a
plain list mirroring the real dispatch queue's FIFO order, since
`queue.Queue` itself can't be peeked into) and `_current_running_job_id`
alongside the existing job state, both updated under the same
`_jobs_lock`, both deliberately NOT persisted (live queue depth, not job
identity -- correctly starts empty after a restart, same as the worker
thread itself does). `get_queue_position()` returns `None` once a job
leaves "queued" (position stops being the relevant signal -- the
browser already has richer progress via status/log_lines by then), so
`server.py` folds it straight into `status_label` itself ("Queued -- 2
jobs ahead of you") rather than a separate field the frontend would
need new code to display -- no `app.js` changes needed, same pattern as
the earlier `"loading"` status addition. Verified with two real jobs
submitted back-to-back: the second stayed at `queue_position=1` for the
entire time the first was actually running, then flipped to `null` the
instant the first finished and the second started.

**Job state now survives a restart** (previously the top limitation
here -- fixed, not just documented as accepted). `webapp/jobs.py`
persists every status change to `webapp/uploads/<job_id>/state.json`
(atomic write: temp file + `os.replace()`, so a crash exactly mid-write
never leaves a corrupt file) and reloads all of them at startup
(`_load_jobs_from_disk()`, called once before the worker thread starts).
A job that was genuinely in-progress (not `done`/`error`) when the
process stopped can't just resume -- the thread running it, and
everything in its local variables, is gone -- so it's marked `error`
with an honest "interrupted by a server restart, please resubmit"
message instead of either silently vanishing (the old 404-forever
behavior) or looking like it's still running with no worker actually
processing it (which would read exactly like the stuck-job problem bug
#29 already spent real effort diagnosing). Verified with a real crash
simulation, not just written: submitted two real jobs, let one finish
normally and force-killed the server while the second was genuinely
mid-`resolving`, restarted, and confirmed via the live API that the
finished job's `status="done"` + its download both still work
correctly, while the interrupted one shows the honest error message --
never a 404, never stuck.

**Upload size is now capped at 20MB per file** (`webapp/server.py`,
matching the `nginx client_max_body_size` already planned in the
deployment runbook -- that layer isn't deployed yet, so this app-level
check is the only enforcement that currently exists). Streamed in 1MB
chunks with the running total checked as it goes, so an oversized upload
is rejected mid-stream -- never fully written to disk, never fully held
in memory -- and the job's upload directory is cleaned up on rejection
rather than left as an orphan. Verified with a real 21MB dummy file:
rejected with a clear message, zero directory created.

### Running it locally

```bash
cd fare_filling_poc_v36
fare_filling_poc\.venv\Scripts\python.exe -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000
```
(run from the project root, so `webapp` is importable as a package). Then
open `http://localhost:8000/`. For real deployment, see
`docs/deployment-runbook.md`.

## 16. Version control & CI

The project previously had no git repository at all. Now initialized
(`main` branch), with `.gitignore` deliberately excluding: rebuildable
virtual environments, `ai_config.env` (local secrets, never committed --
see section 4), generated run output (`pipeline_output_new_filing.json`,
`run_log_*.txt`, `SQ Fare Filing_*.xlsx`), `webapp/uploads/` +
`webapp/outputs/` (real fare-filing data passes through here), **and,
deliberately, the real production pricebook samples in `input_files/`
and generated business documents in `reports/`** -- both are treated as
data/deliverables rather than source, and the pricebook data specifically
is real business data that shouldn't be committed without a separate,
explicit decision to do so.

### CI (`.gitlab-ci.yml`)

Scoped deliberately narrow: catches import/syntax breakage and the exact
regression classes already found once by hand, rather than attempting
full pipeline coverage a shared CI runner can't realistically provide (no
route to the self-hosted AI endpoint from a CI runner; real pricebook
fixtures are intentionally not committed, see above).

| Job | Catches |
|---|---|
| `import-sanity` | A broken import or syntax error in any pipeline module or category resolver -- runs `importlib.import_module()` on every core module and `ast.parse()` on every `categories/*.py` file |
| `webapp-static-consistency` | An `index.html`/`app.js` element-id mismatch -- automates the exact check that was run by hand after every `webapp/static/` edit during development |
| `webapp-smoke-test` (`ci/browser_smoke_test.py`) | A real headless-browser click-through against a live `uvicorn` instance the job starts itself. Regression-guards the hidden-required-field bug above (empty submit must show validation AND make no backend call), and confirms a filled submission reaches the backend end-to-end using a synthetic blank `.xlsx` (no real pricebook data or reachable AI endpoint needed -- expects and confirms a clean RULE-detection error, which proves the request/response/polling plumbing works without depending on AI) |
| `pipeline-regression-real-files` | Manual, `allow_failure: true` placeholder -- NOT wired up automatically. Its fixture files (`input_files_type2/`, `input_files_type3/`, the original `V1-ABC1 Type1.xlsm`) no longer exist on disk (section 5/9). Left visibly unfinished in the pipeline rather than silently absent. |

### Deployment

CD is deliberately not "auto-deploy on merge" -- the target host is
managed by Ops/Infra (no direct access from this project), and there's
no authentication layer yet to make an unattended production push a safe
default. The full handoff procedure is `docs/deployment-runbook.md`:
environment setup, a ready-to-use `systemd` unit, an `nginx` reverse-
proxy config, the storage-retention gap (needs a decision, not yet
fixed), and exactly what a service restart loses (see section 15's
in-memory-state limitation) -- written for someone who has never seen
this codebase to execute end to end.
