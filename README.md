# Fare Filling Automation

Reads airline fare-filing pricebook files (`.xlsm`), interprets each fare
category's rule text (deterministically where possible, with AI assistance
where the text is genuinely free-form), and writes the result into the
airline's Excel filing template. A parallel JSON output is also produced
for downstream automation.

## How it works

```
Upload form (webapp/) or CLI (run_new_filing.py)
  -> match each pricebook file to its RULE (by file content, not filename)
  -> for each RULE, resolve every category once (CAT01 ... CAT33)
  -> cross-join the result across every TARIFF belonging to that RULE
  -> write each category's rows into the template at verified cell positions
```

One pricebook file corresponds to one RULE, and a RULE may have several
TARIFFs. Category data is resolved once per RULE and repeated per TARIFF.

Three filing classification types are supported (Type 1, 2, 3). The type is
chosen on the upload form (or CLI flag); it is not auto-detected.

## Category resolution order

Each category resolver follows the same decision order:

1. No field-level mapping exists for the category -> only common fields are
   written (a free-text note may still be captured in the JSON output).
2. The text refers to another tab ("REFER TO ...") or a structured flag column
   -> deterministic lookup / regex parsing.
3. The text is the standard "no restriction" phrase -> blank entry, no AI call.
4. An explicit extraction rule exists for the pattern -> deterministic parsing.
5. Otherwise -> AI fallback, using the category's spec in `ai_specs/`.

Every AI-derived value is marked low-confidence, flagged for human review,
and highlighted per cell in the Excel output.

## AI extraction

- One shared engine (`ai_engine.py`) builds the prompt, calls the model and
  parses the JSON reply. Category-specific instructions and few-shot examples
  live in `ai_specs/*.yaml`, not in Python.
- Field labels shown to the model come straight from the template's own
  header cells, so the model sees the same labels a human filer does.
- Successful extractions are cached by (spec, normalized condition text,
  fields). Whitespace differences are collapsed first. Two RULEs that share
  the same condition text therefore get the same answer and cost one call
  instead of two. Cache hits appear in the run log as `CACHED`.
- Provider settings are read from a local, uncommitted `ai_config.env`.
  Nothing in this repository documents endpoints, keys or model choices.
  If no provider is configured, calls fall back to a clearly labeled mock
  that must never be treated as a real result.

## Repository layout

```
fare_filling_poc/     Pipeline: loaders, category resolvers, AI engine, template writer
  categories/         One resolver per category (cat01 ... cat33)
  ai_specs/           Per-category AI instructions and examples (yaml)
  template_columns.py Where each field lives in the template (data only)
  template_writer.py  How values are written (row shifting, styles, normalization)
  xlsm_loader.py      Reads real pricebook files
  run_new_filing.py   CLI entry point
webapp/               FastAPI upload form, job queue, audit trail
tests/                Fast, synthetic unit tests (pytest)
template/             The Excel filing template
docs/                 Operational documentation
ci/                   CI helper scripts
```

## Running locally

Web form (from the project root):

```bash
fare_filling_poc\.venv\Scripts\python.exe -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000
```

Then open the form in a browser. Jobs run one at a time through a queue;
status and queue position are shown on the page, and the finished file
downloads automatically.

CLI:

```bash
cd fare_filling_poc
.venv\Scripts\python.exe run_new_filing.py --sheet-type 1 --wo-id <WO_ID> \
    --file "<path to pricebook>" --rule-tariff "RULE(TARIFF1,TARIFF2)"
```

Each run writes the filled template, a JSON dump, and a timestamped run log
with per-call timing and a summary.

## Tests

```bash
fare_filling_poc\.venv\Scripts\python.exe -m pytest tests/ -v
```

## Web app behavior worth knowing

- Uploads are limited to `.xlsm`/`.xlsx`, 20 MB per file, validated on the server.
- Work-order IDs are restricted to a safe character set before use in file names.
- Submissions are rate limited per IP and recorded in an append-only audit log.
- Job state is persisted, so a restart marks interrupted jobs as failed rather
  than losing them silently.
- There is no authentication and no upload/output retention policy yet.
  See `docs/deployment-runbook.md` before running unattended.

## Deployment

See `docs/deployment-runbook.md`.
