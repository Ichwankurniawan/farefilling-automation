import json
import sys
sys.path.insert(0, "/home/claude/fare_filling_poc")

from pricebook_data import PricebookData
from pipeline import run_pipeline

# CAT01 condition is genuine free text -- neither "REFER TO..." nor
# "NONE UNLESS OTHERWISE SPECIFIED" -- to prove the AI path actually fires
# end-to-end through the real pipeline (not just the isolated prompt test).
fare_rules = [
    {"CAT": "01", "FARE RULE CONDITIONS": "Fare only valid for passengers holding a valid student ID, aged 12 to 25.",
     "IPRG": "IPRG AB60"},
    {"CAT": "02", "FARE RULE CONDITIONS": "NONE UNLESS OTHERWISE SPECIFIED", "IPRG": "IPRG AB60"},
    {"CAT": "03", "FARE RULE CONDITIONS": "NONE UNLESS OTHERWISE SPECIFIED", "IPRG": "IPRG AB60"},
    {"CAT": "04", "FARE RULE CONDITIONS": "NONE UNLESS OTHERWISE SPECIFIED", "IPRG": "IPRG AB60"},
]

pricebook = PricebookData(rule_id="ABC1", fare_rules_rows=fare_rules, tabs={})

anchor_rows = [{"RULE": "ABC1", "TARIFF": "ABCD1F", "PRICEBOOK_NAME": "V1-ABC1 Type1", "sheet_type": 1}]
pricebook_lookup = {"ABC1": pricebook}

output = run_pipeline(anchor_rows, pricebook_lookup)

print("CAT01 result (should be AI_EXTRACTED):")
print(json.dumps(output["CAT01"][0], indent=2))
