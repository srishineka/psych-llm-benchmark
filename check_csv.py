import pandas as pd
df = pd.read_csv('d:/psych_llm_benchmark/logs/summary/summary_metrics.csv')
print(f'Total rows: {len(df)}')
missing_llm = df[df['llm_diagnostic_score'].isna() | df['llm_overall_score'].isna()]
print(f'Rows missing LLM scores: {len(missing_llm)}')
if len(missing_llm) > 0:
    print(missing_llm[['session_id', 'condition', 'therapist_model']])
