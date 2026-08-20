"""
Run the fare-filing pipeline against NEW pricebook files and write the
result into the real Excel filing template -- driven entirely by CLI flags.

This is the stand-in for the "upload form" that CLAUDE.md section 2 notes
isn't built yet -- until that exists, this is where you pass in the Type,
WO ID, and RULE & TARIFF for a new batch of files to test.

USAGE
-----
  Explicit pairing (one --rule-tariff per --file, in matching order):
    python run_new_filing.py --sheet-type 1 --wo-id 112233 \
        --file "C:\\path\\HKF1.xlsm" --rule-tariff "HKF1(ABCD1)" \
        --file "C:\\path\\HKF2.xlsm" --rule-tariff "HKF2(ABCD1,FGHIJK)"

  Form-style intake (mirrors the real upload form: one free-text Rule &
  Tariff field, files uploaded with no per-file RULE tag at all -- each
  file's RULE is detected from ITS OWN internal "ATPCO Rule No." cell
  and matched against the typed specs; see intake_matcher.py for why
  filename/upload-order matching were ruled out):
    python run_new_filing.py --sheet-type 1 --wo-id 112233 \
        --rule-tariff-text "HKF1 (ABCD1), HKF2 (ABCD1, FGHIJK)" \
        --file "C:\\path\\HKF1.xlsm" --file "C:\\path\\HKF2.xlsm"

FLAGS
-----
  --sheet-type       1, 2, or 3 -- every --file in this run must be this
                     same type (run the command again separately for a
                     different type)
  --wo-id            Work Order ID, written to the output template's cover cell (B1)
  --file             Path to one pricebook .xlsm file. Repeat once per file.
  --rule-tariff      "RULE(TARIFF1,TARIFF2,...)" for the --file immediately
                     paired with it, in order -- e.g. "HKF2(ABCD1,FGHIJK)" for
                     a RULE filed under two TARIFFs. One per --file, same order.
                     Mutually exclusive with --rule-tariff-text.
  --rule-tariff-text The whole form field as one string, e.g.
                     "HKF1 (ABCD1), HKF2 (ABCD1, FGHIJK)" -- files are matched
                     to RULEs by content, not by position. Mutually exclusive
                     with --rule-tariff; when given, --file needs no pairing.
  --output           (optional) output .xlsx path. Defaults to
                     "SQ Fare Filing_<WO_ID>_Type<N>.xlsx" next to this script.

The script prints progress as it runs (per-RULE category resolution, AI
calls with timing/token usage), writes a plain-text run log
(run_log_<WO_ID>_Type<N>_<ddmmyyyy_hhmmss>.txt) alongside this script,
writes a JSON dump of
the full pipeline output (pipeline_output_new_filing.json), and writes the
filled-in Excel template to --output. The run log and pipeline JSON are
kept separate on purpose -- the JSON stays pure filing data, the log is
just progress/diagnostics and never touches the JSON or the .xlsx.
"""
import argparse
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import run_logger
from intake_matcher import match_files_to_rules

TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "template", "SQ Fare Filling Template.xlsx")

RULE_TARIFF_RE = re.compile(r"^\s*([A-Za-z0-9]+)\s*\(\s*([^)]+?)\s*\)\s*$")


def _parse_rule_tariff(spec):
    """Parses "RULE(TARIFF1,TARIFF2)" -> (rule, [tariff1, tariff2])."""
    m = RULE_TARIFF_RE.match(spec)
    if not m:
        raise argparse.ArgumentTypeError(
            f'--rule-tariff {spec!r} must look like "RULE(TARIFF1,TARIFF2)"'
        )
    rule = m.group(1)
    tariffs = [t.strip() for t in m.group(2).split(",") if t.strip()]
    if not tariffs:
        raise argparse.ArgumentTypeError(f"--rule-tariff {spec!r} has no TARIFF codes")
    return rule, tariffs


def parse_args():
    p = argparse.ArgumentParser(
        description="Run the fare-filing pipeline against new pricebook files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--sheet-type", type=int, required=True, choices=(1, 2, 3),
                    help="1, 2, or 3 -- applies to every --file in this run")
    p.add_argument("--wo-id", required=True, help="Work Order ID (written to the template's B1 cell)")
    p.add_argument("--file", action="append", dest="files", default=[], required=True,
                    help="Path to a pricebook .xlsm file. Repeat once per file.")
    p.add_argument("--rule-tariff", action="append", dest="rule_tariffs", default=[],
                    help='"RULE(TARIFF1,TARIFF2)" paired in order with --file. '
                         'Mutually exclusive with --rule-tariff-text.')
    p.add_argument("--rule-tariff-text", default=None,
                    help='The whole form field as one string, e.g. "HKF1 (ABCD1), HKF2 (ABCD1, FGHIJK)" -- '
                         'files matched to RULEs by content, not position. Mutually exclusive with --rule-tariff.')
    p.add_argument("--output", default=None,
                    help='Output .xlsx path. Defaults to "SQ Fare Filing_<WO_ID>_Type<N>.xlsx" next to this script.')
    args = p.parse_args()

    if args.output is None:
        args.output = os.path.join(BASE_DIR, f"SQ Fare Filing_{args.wo_id}_Type{args.sheet_type}.xlsx")

    for path in args.files:
        if not os.path.isfile(path):
            p.error(f"--file not found: {path}")

    if args.rule_tariff_text and args.rule_tariffs:
        p.error("--rule-tariff and --rule-tariff-text are mutually exclusive -- use one or the other")

    if args.rule_tariff_text:
        try:
            matched = match_files_to_rules(args.files, args.rule_tariff_text)
        except ValueError as e:
            p.error(str(e))
        files = matched  # already [{"path":..., "rule":..., "tariffs":...}, ...]
    else:
        if not args.rule_tariffs:
            p.error("need either --rule-tariff (one per --file) or --rule-tariff-text (the whole form field)")
        if len(args.files) != len(args.rule_tariffs):
            p.error(f"got {len(args.files)} --file but {len(args.rule_tariffs)} --rule-tariff -- "
                    f"need exactly one --rule-tariff per --file, in matching order "
                    f"(or use --rule-tariff-text instead)")
        files = []
        for path, spec in zip(args.files, args.rule_tariffs):
            try:
                rule, tariffs = _parse_rule_tariff(spec)
            except argparse.ArgumentTypeError as e:
                p.error(str(e))
            files.append({"path": path, "rule": rule, "tariffs": tariffs})

    return args, files


def main():
    args, files = parse_args()
    sheet_type = args.sheet_type

    timestamp = time.strftime("%d%m%Y_%H%M%S")
    log_path = os.path.join(BASE_DIR, f"run_log_{args.wo_id}_Type{sheet_type}_{timestamp}.txt")
    run_logger.set_log_file(log_path)
    run_logger.log(f"Starting run: sheet_type={sheet_type} wo_id={args.wo_id} "
                    f"files={[f['rule'] for f in files]}")

    # Build anchor_rows (one per RULE+TARIFF, cross-joined) and
    # pricebook_lookup (one per RULE) the same way every test_*.py script
    # in this project does.
    anchor_rows = []
    pricebook_lookup = {}
    for f in files:
        rule = f["rule"]
        pricebook_name = os.path.splitext(os.path.basename(f["path"]))[0]

        if sheet_type == 1:
            from xlsm_loader import load_pricebook_from_xlsm
            pricebook_lookup[rule] = load_pricebook_from_xlsm(f["path"], rule)
        elif sheet_type == 2:
            from xlsm_loader import load_pricebook_type2
            pricebook_lookup[rule] = load_pricebook_type2(f["path"], rule)
        else:
            from xlsm_loader import load_pricebook_type3
            pricebook_lookup[rule] = load_pricebook_type3(f["path"], rule)

        for tariff in f["tariffs"]:
            anchor_rows.append({
                "RULE": rule, "TARIFF": tariff,
                "PRICEBOOK_NAME": pricebook_name, "sheet_type": sheet_type,
            })

    if sheet_type == 1:
        from pipeline import run_pipeline
        from template_writer import write_to_template

        output = run_pipeline(anchor_rows, pricebook_lookup)

        run_logger.log("Pipeline resolution complete:")
        for sheet_name, rows in output.items():
            run_logger.log(f"  {sheet_name}: {len(rows)} rows")

        with open(os.path.join(BASE_DIR, "pipeline_output_new_filing.json"), "w") as fh:
            json.dump(output, fh, indent=2, default=str)

        write_to_template(
            template_path=TEMPLATE_PATH,
            pipeline_output=output,
            anchor_rows=anchor_rows,
            output_path=args.output,
            wo_id=args.wo_id,
        )

    else:
        from pipeline import run_pipeline_type2_3
        from template_writer import write_to_template_type2

        output_main, output_poo = run_pipeline_type2_3(anchor_rows, pricebook_lookup)

        run_logger.log("Main output row counts:")
        for k, v in output_main.items():
            run_logger.log(f"  {k}: {len(v)} rows")
        run_logger.log("POO output row counts:")
        for k, v in output_poo.items():
            run_logger.log(f"  {k}: {len(v)} rows")

        with open(os.path.join(BASE_DIR, "pipeline_output_new_filing.json"), "w") as fh:
            json.dump({"main": output_main, "poo": output_poo}, fh, indent=2, default=str)

        write_to_template_type2(
            template_path=TEMPLATE_PATH,
            output_main=output_main,
            output_poo=output_poo,
            anchor_rows=anchor_rows,
            output_path=args.output,
            wo_id=args.wo_id,
        )

    run_logger.log(f"Done. Wrote {args.output}")
    run_logger.log_summary()


if __name__ == "__main__":
    main()
