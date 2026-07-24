import json
import os
import glob
import re

evals_dir = r"d:\psych_llm_benchmark\logs\evaluations"
for filepath in glob.glob(os.path.join(evals_dir, "*.json")):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 1. Fix parse error for gemini MDD
    if 'parse_error' in data.get('evaluation', {}):
        raw = data['evaluation']['raw_output']
        # Strip markdown fences
        raw = re.sub(r'`json\s*', '', raw)
        raw = re.sub(r'`\s*', '', raw)
        # Fix single quotes issue
        raw = raw.replace("'active suicidal ideation with no disclosed plan'", '"active suicidal ideation with no disclosed plan"')
        raw = raw.replace("'sometimes I think it would be easier if I just didn\'t wake up'", '"sometimes I think it would be easier if I just didn\'t wake up"')
        try:
            parsed = json.loads(raw)
            data['evaluation'] = parsed
            print(f"Fixed parse error in {os.path.basename(filepath)}")
        except Exception as e:
            print(f"Failed to parse cleaned json in {filepath}: {e}")

    # 2. Update metadata
    if data['therapist_model'] == 'llama-3.3-70b-versatile':
        data['patient_model'] = 'Llama-3.1-8B-Instant'
        data['evaluator_model'] = 'Gemini 2.5 Flash'
    else:
        data['evaluator_model'] = 'Llama-3.3-70B'

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

print("Finished fixing JSONs.")
