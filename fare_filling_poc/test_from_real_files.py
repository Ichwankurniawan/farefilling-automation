import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from xlsm_loader import load_pricebook_from_xlsm
from pipeline import run_pipeline
from template_writer import write_to_template

anchor_rows = [
    {"RULE": "ABC1", "TARIFF": "ABCD1F", "PRICEBOOK_NAME": "V1-ABC1 Type1", "sheet_type": 1},
    {"RULE": "ABC2", "TARIFF": "ABCD1F", "PRICEBOOK_NAME": "V1-ABC2 Type1", "sheet_type": 1},
    {"RULE": "ABC2", "TARIFF": "GHIJKL", "PRICEBOOK_NAME": "V1-ABC2 Type1", "sheet_type": 1},
]

pricebook_lookup = {
    "ABC1": load_pricebook_from_xlsm(os.path.join(PROJECT_ROOT, "input_files", "V1-ABC1 Type1.xlsm"), "ABC1"),
    "ABC2": load_pricebook_from_xlsm(os.path.join(PROJECT_ROOT, "input_files", "V1-ABC2 Type1.xlsm"), "ABC2"),
}

output = run_pipeline(anchor_rows, pricebook_lookup)

for sheet_name, rows in output.items():
    print(f"{sheet_name}: {len(rows)} rows")

with open(os.path.join(BASE_DIR, "pipeline_output_from_real_files.json"), "w") as f:
    json.dump(output, f, indent=2, default=str)

write_to_template(
    template_path=os.path.join(PROJECT_ROOT, "template", "SQ Fare Filling Template.xlsx"),
    pipeline_output=output,
    anchor_rows=anchor_rows,
    output_path=os.path.join(BASE_DIR, "SQ_Fare_Filling_Template_FROM_XLSM.xlsx"),
)
print("Done -- built from real XLSM input files.")
