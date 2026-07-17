"""
Loads exported logs (logs/summary/summary_metrics.csv, logs/evaluations/*.json,
logs/transcripts/*.json) back into memory for visualization and qualitative
"why" analysis.
"""

import json
import os
from typing import List, Dict, Optional

import pandas as pd

import config


def load_all_evaluations(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Loads the flattened summary CSV (one row per session) into a DataFrame."""
    csv_path = csv_path or config.SUMMARY_CSV_PATH
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(
            f"No summary CSV found at {csv_path}. Run run_benchmark.py first."
        )
    return pd.read_csv(csv_path)


def load_full_records(evaluations_dir: Optional[str] = None,
                       transcripts_dir: Optional[str] = None) -> List[Dict]:
    """
    Joins each session's evaluation JSON with its transcript JSON by
    session_id, producing a list of full records for deep qualitative
    analysis (e.g. WhyAnalyzer needs the actual flagged transcript turns,
    not just the numeric scores).
    """
    evaluations_dir = evaluations_dir or config.EVALUATIONS_DIR
    transcripts_dir = transcripts_dir or config.TRANSCRIPTS_DIR

    records = []
    for fname in os.listdir(evaluations_dir):
        if not fname.endswith(".json"):
            continue
        session_id = fname[:-5]

        with open(os.path.join(evaluations_dir, fname)) as f:
            eval_record = json.load(f)

        transcript_path = os.path.join(transcripts_dir, fname)
        transcript_record = None
        if os.path.isfile(transcript_path):
            with open(transcript_path) as f:
                transcript_record = json.load(f)

        records.append({
            "session_id": session_id,
            "condition": eval_record.get("condition"),
            "therapist_model": eval_record.get("therapist_model"),
            "patient_model": eval_record.get("patient_model"),
            "evaluation": eval_record.get("evaluation", {}),
            "transcript": transcript_record.get("turns") if transcript_record else None,
        })
    return records
