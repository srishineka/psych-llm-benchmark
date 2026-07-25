"""
Consolidation script: collects ALL evaluation data from scattered log_*
directories, deduplicates, recomputes formula metrics consistently, writes
a single clean summary CSV into logs/summary/, and generates charts.

Usage:
    python consolidate_logs.py
"""

import json
import csv
import os
import sys
import glob
import shutil
from collections import defaultdict

import pandas as pd
import numpy as np

import config
from analytics.metrics import compute_formula_metrics
from analytics.visualize import generate_all_charts

# ── Directories that hold model-specific log batches ──────────────────────
BASE_DIR = config.PROJECT_ROOT
LOG_DIRS = sorted(glob.glob(str(BASE_DIR / "log_*")))

ALL_CONDITIONS = config.ALL_CONDITIONS  # The 9 canonical conditions


def collect_all_evaluations():
    """
    Walk every log_*/…/evaluations/*.json and logs/evaluations/*.json, load each evaluation,
    and deduplicate by session_id (keep last).  Also loads the matching
    transcript if available so we can recompute formula metrics.
    """
    raw_records = {}  # session_id -> record dict

    eval_files = glob.glob(
        os.path.join(str(BASE_DIR), "log_*", "**", "evaluations", "*.json"),
        recursive=True,
    ) + glob.glob(
        os.path.join(str(BASE_DIR), "logs", "evaluations", "*.json"),
        recursive=True,
    )

    for fp in eval_files:
        if ".gitkeep" in fp:
            continue
        with open(fp) as f:
            data = json.load(f)

        sid = data.get("session_id")
        if not sid:
            continue

        # Try to find matching transcript JSON using the actual session_id or filename
        eval_dir = os.path.dirname(fp)
        run_dir = os.path.dirname(eval_dir)
        if os.path.basename(run_dir) == "logs":
            transcript_path = os.path.join(run_dir, "transcripts", os.path.basename(fp))
        else:
            transcript_path = os.path.join(run_dir, "transcripts", f"{sid}.json")
            
        turns = []
        if os.path.isfile(transcript_path):
            with open(transcript_path) as f:
                tdata = json.load(f)
            turns = tdata.get("turns", [])

        raw_records[sid] = {
            "session_id": sid,
            "condition": data.get("condition"),
            "therapist_model": data.get("therapist_model"),
            "patient_model": data.get("patient_model"),
            "timestamp": data.get("timestamp"),
            "evaluation": data.get("evaluation", {}),
            "turns": turns,
            "source_eval_path": fp,
            "source_transcript_path": transcript_path if os.path.isfile(transcript_path) else None,
        }

    print(f"Collected {len(raw_records)} unique sessions from {len(eval_files)} JSON files.")
    return raw_records


def build_summary_row(record):
    """Build a flat summary dict from one evaluation record, and extract mapping rows."""
    evaluation = record["evaluation"]
    diag = evaluation.get("diagnostic_scoring_accuracy", {}) or {}
    safety = evaluation.get("safety_red_line_adherence", {}) or {}
    coherence = evaluation.get("conversational_coherence", {}) or {}
    empathy = evaluation.get("empathy_alignment_and_bias", {}) or {}
    bl = empathy.get("barrett_lennard_dimensions", {}) or {}

    row = {
        "session_id": record["session_id"],
        "condition": record["condition"],
        "therapist_model": record["therapist_model"],
        "patient_model": record["patient_model"],
        "timestamp": record["timestamp"],
        "llm_diagnostic_score": diag.get("score_0_to_10"),
        "llm_safety_score": safety.get("score_0_to_10"),
        "llm_coherence_score": coherence.get("score_0_to_10"),
        "llm_empathy_score": empathy.get("score_0_to_10"),
        "bl_level_of_regard": bl.get("level_of_regard"),
        "bl_empathic_understanding": bl.get("empathic_understanding"),
        "bl_unconditionality_of_regard": bl.get("unconditionality_of_regard"),
        "bl_congruence": bl.get("congruence"),
        "llm_overall_score": evaluation.get("overall_score_0_to_100"),
        "missed_risk_markers_count": len(safety.get("missed_risk_markers", []) or []),
        "hallucinations_count": len(safety.get("hallucinated_clinical_claims", []) or []),
        "bias_flags_count": len(empathy.get("western_centric_bias_flags", []) or []),
    }

    criteria_rows = []
    risk_rows = []

    # Recompute formula metrics consistently
    try:
        formula = compute_formula_metrics(
            record["condition"], record["turns"], evaluation
        )
        row.update(formula.as_dict())

        if hasattr(formula, "criteria_mapping") and formula.criteria_mapping:
            for idx, (text, status) in enumerate(formula.criteria_mapping, 1):
                criteria_rows.append({
                    "session_id": record["session_id"],
                    "condition": record["condition"],
                    "therapist_model": record["therapist_model"],
                    "criterion_number": idx,
                    "criterion_text": text,
                    "status": status,
                })
        if hasattr(formula, "risk_mapping") and formula.risk_mapping:
            for idx, (text, status) in enumerate(formula.risk_mapping, 1):
                risk_rows.append({
                    "session_id": record["session_id"],
                    "condition": record["condition"],
                    "therapist_model": record["therapist_model"],
                    "risk_marker_number": idx,
                    "risk_marker_text": text,
                    "status": status,
                })
    except Exception as e:
        print(f"  WARNING: Could not compute formula metrics for "
              f"{record['session_id'][:8]}.. ({record['condition']}): {e}")
        # Fill with NaN
        row.update({
            "formula_cer": None,
            "formula_recall_safety": None,
            "formula_hallucination_rate": None,
            "formula_safety_score": None,
            "formula_coherence_score": None,
            "formula_empathy_score": None,
            "formula_overall_score": None,
            "therapist_turns": None,
        })

    return row, criteria_rows, risk_rows


def deduplicate_per_model(records):
    """
    For models with duplicate conditions (e.g. ChatDoctor has 2 BPD sessions),
    keep only the most recent session per (therapist_model, condition) pair.
    """
    by_key = {}
    for sid, rec in records.items():
        key = (rec["therapist_model"], rec["condition"])
        existing = by_key.get(key)
        if existing is None or (rec["timestamp"] or "") > (existing["timestamp"] or ""):
            by_key[key] = rec

    deduped = {rec["session_id"]: rec for rec in by_key.values()}
    dropped = len(records) - len(deduped)
    if dropped:
        print(f"Deduplicated: dropped {dropped} duplicate (model, condition) pair(s), "
              f"keeping most recent. {len(deduped)} sessions remain.")
    return deduped


def write_clean_csv(rows, output_path):
    """Write the clean, consolidated summary CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Sort for readability: by model, then condition
    if "therapist_model" in df.columns and "condition" in df.columns:
        df = df.sort_values(["therapist_model", "condition"]).reset_index(drop=True)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")
    return df


def print_coverage_report(df):
    """Print a coverage matrix: which models have which conditions."""
    models = sorted(df["therapist_model"].unique())
    print(f"\n{'='*70}")
    print("COVERAGE REPORT: Models × Conditions")
    print(f"{'='*70}")
    print(f"{'Model':<45} | {'Conditions':>10} | Missing")
    print("-" * 70)
    for model in models:
        model_df = df[df["therapist_model"] == model]
        conditions = set(model_df["condition"].unique())
        missing = sorted(set(ALL_CONDITIONS) - conditions)
        status = "COMPLETE" if not missing else ", ".join(missing)
        print(f"{model:<45} | {len(conditions):>10} | {status}")
    print(f"{'='*70}\n")


def copy_to_common_logs(records):
    """
    Copy the correct (deduplicated) evaluation and transcript JSONs
    from the scattered log_* directories into the common logs/ folder.
    Clears the target directories of files that are not active.
    """
    eval_dir = str(config.EVALUATIONS_DIR)
    trans_dir = str(config.TRANSCRIPTS_DIR)

    os.makedirs(eval_dir, exist_ok=True)
    os.makedirs(trans_dir, exist_ok=True)

    keep_filenames = set()

    # Step 1: Copy every deduplicated session to a clean {model}_{condition}.json filename
    for sid, rec in records.items():
        safe_model = rec['therapist_model'].replace("/", "_").replace("\\", "_")
        safe_cond = rec['condition'].replace(" ", "_")
        std_filename = f"{safe_model}_{safe_cond}.json"
        keep_filenames.add(std_filename)

        eval_src = rec["source_eval_path"]
        eval_dst = os.path.join(eval_dir, std_filename)
        if os.path.abspath(eval_src) != os.path.abspath(eval_dst):
            if os.path.isfile(eval_src):
                shutil.copy2(eval_src, eval_dst)

        trans_src = rec.get("source_transcript_path")
        if trans_src and os.path.isfile(trans_src):
            trans_dst = os.path.join(trans_dir, std_filename)
            if os.path.abspath(trans_src) != os.path.abspath(trans_dst):
                shutil.copy2(trans_src, trans_dst)

    # Step 2: Delete any file in target directories that is NOT in our 72 standardized filenames
    for target_dir in [eval_dir, trans_dir]:
        if os.path.exists(target_dir):
            for existing_file in os.listdir(target_dir):
                if existing_file.endswith(".json") and existing_file not in keep_filenames:
                    file_to_remove = os.path.join(target_dir, existing_file)
                    try:
                        os.remove(file_to_remove)
                    except Exception as e:
                        print(f"Warning: Could not remove stale file {file_to_remove}: {e}")

    print(f"Copied clean standardized logs and removed duplicates/UUID files:\n  Evaluations: {len(records)} -> {eval_dir}\n  Transcripts: {len(records)} -> {trans_dir}")


def combine_why_reports():
    """
    Finds all generated why_reports from partial batches and combines them
    by model into config.WHY_REPORTS_DIR.
    """
    out_dir = str(config.WHY_REPORTS_DIR)
    os.makedirs(out_dir, exist_ok=True)

    reports = glob.glob(os.path.join(str(BASE_DIR), "log_*", "**", "why_reports", "*.md"), recursive=True)
    models = defaultdict(list)
    for r in reports:
        model_file = os.path.basename(r)
        models[model_file].append(r)

    count = 0
    for model_file, paths in models.items():
        combined_text = []
        model_name = model_file.replace("_why_report.md", "").replace("_", "/")
        combined_text.append(f"# Combined Root-Cause Analysis: {model_name}\n")
        
        for p in sorted(paths):
            batch_folder = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p))))
            combined_text.append(f"\n## Batch: {batch_folder}\n")
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
                if content.startswith("# Root-Cause Analysis"):
                    content = content.split("\n", 1)[1].strip()
                combined_text.append(content)
                
        out_path = os.path.join(out_dir, model_file)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(combined_text))
        count += 1
        
    print(f"Combined why reports for {count} models -> {out_dir}")


def main():
    print("=" * 60)
    print("CONSOLIDATING ALL LOG DATA")
    print("=" * 60)

    # Step 1: Collect all evaluations from log_* directories
    records = collect_all_evaluations()

    # Step 2: Deduplicate — keep one session per (model, condition)
    records = deduplicate_per_model(records)

    # Step 3: Copy correct JSONs into common logs/ folder
    copy_to_common_logs(records)

    # Step 4: Build summary rows with consistent formula metrics
    print("\nRecomputing formula metrics for all sessions...")
    rows = []
    all_criteria_rows = []
    all_risk_rows = []
    for sid, rec in sorted(records.items()):
        row, c_rows, r_rows = build_summary_row(rec)
        rows.append(row)
        all_criteria_rows.extend(c_rows)
        all_risk_rows.extend(r_rows)

    # Step 5: Write clean consolidated CSVs
    output_csv = str(config.SUMMARY_CSV_PATH)
    df = write_clean_csv(rows, output_csv)

    criteria_csv = os.path.join(os.path.dirname(output_csv), "criteria_mapping.csv")
    write_clean_csv(all_criteria_rows, criteria_csv)

    risk_csv = os.path.join(os.path.dirname(output_csv), "risk_mapping.csv")
    write_clean_csv(all_risk_rows, risk_csv)

    # Step 6: Print coverage report
    print_coverage_report(df)

    # Step 7: Generate charts
    print("Generating charts from consolidated data...")
    os.makedirs(str(config.FIGURES_DIR), exist_ok=True)
    chart_paths = generate_all_charts(df, output_dir=str(config.FIGURES_DIR))
    for name, path in chart_paths.items():
        print(f"  {name} -> {path}")

    # Step 7: Also generate per-model charts
    models_with_full_data = []
    for model in df["therapist_model"].unique():
        model_df = df[df["therapist_model"] == model]
        if len(model_df["condition"].unique()) == 9:
            models_with_full_data.append(model)

    if models_with_full_data:
        print(f"\nGenerating per-model charts for {len(models_with_full_data)} models with full 9-condition data...")
        for model in models_with_full_data:
            model_df = df[df["therapist_model"] == model]
            safe_name = model.replace("/", "_")
            model_fig_dir = os.path.join(str(config.FIGURES_DIR), safe_name)
            os.makedirs(model_fig_dir, exist_ok=True)
            model_charts = generate_all_charts(model_df, output_dir=model_fig_dir)
            print(f"  {model}: {len(model_charts)} charts -> {model_fig_dir}")
            
    # Step 8: Combine why reports
    print("\nCombining why reports...")
    combine_why_reports()

    print("\n>> CONSOLIDATION COMPLETE")
    print(f"  Summary CSV: {output_csv}")
    print(f"  Charts:      {config.FIGURES_DIR}")


if __name__ == "__main__":
    main()
