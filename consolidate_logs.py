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
    Walk every log_*/…/evaluations/*.json, load each evaluation,
    and deduplicate by session_id (keep last).  Also loads the matching
    transcript if available so we can recompute formula metrics.
    """
    raw_records = {}  # session_id -> record dict

    eval_files = glob.glob(
        os.path.join(str(BASE_DIR), "log_*", "**", "evaluations", "*.json"),
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

        # Try to find matching transcript JSON using the actual session_id
        eval_dir = os.path.dirname(fp)
        run_dir = os.path.dirname(eval_dir)
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
    """Build a flat summary dict from one evaluation record."""
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

    # Recompute formula metrics consistently
    try:
        formula = compute_formula_metrics(
            record["condition"], record["turns"], evaluation
        )
        row.update(formula.as_dict())
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

    return row


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

    df = pd.DataFrame(rows)
    # Sort for readability: by model, then condition
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
    Clears the target directories first to remove stale files.
    """
    eval_dir = str(config.EVALUATIONS_DIR)
    trans_dir = str(config.TRANSCRIPTS_DIR)

    # Clear existing files (keep .gitkeep)
    for d in (eval_dir, trans_dir):
        for f in os.listdir(d):
            if f == ".gitkeep":
                continue
            os.remove(os.path.join(d, f))

    eval_count = 0
    trans_count = 0
    missing_trans = []

    for sid, rec in sorted(records.items()):
        safe_model = rec['therapist_model'].replace("/", "_").replace("\\", "_")
        safe_cond = rec['condition'].replace(" ", "_")
        fname = f"{safe_model}_{safe_cond}.json"

        # Copy evaluation JSON
        src_eval = rec.get("source_eval_path")
        if src_eval and os.path.isfile(src_eval):
            shutil.copy2(src_eval, os.path.join(eval_dir, fname))
            eval_count += 1

        # Copy transcript JSON
        src_trans = rec.get("source_transcript_path")
        if src_trans and os.path.isfile(src_trans):
            shutil.copy2(src_trans, os.path.join(trans_dir, fname))
            trans_count += 1
        else:
            missing_trans.append(f"{rec['therapist_model']}/{rec['condition']}")

    print(f"\nCopied to common logs/:")
    print(f"  Evaluations: {eval_count} -> {eval_dir}")
    print(f"  Transcripts: {trans_count} -> {trans_dir}")
    if missing_trans:
        print(f"  Missing transcripts ({len(missing_trans)}): {', '.join(missing_trans)}")


def combine_why_reports():
    """
    Finds all generated why_reports from partial batches and combines them
    by model into logs/why_reports.
    """
    out_dir = os.path.join(str(BASE_DIR), "logs", "why_reports")
    os.makedirs(out_dir, exist_ok=True)
    
    # Clear old files
    for f in os.listdir(out_dir):
        if f.endswith(".md"):
            os.remove(os.path.join(out_dir, f))

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
    for sid, rec in sorted(records.items()):
        row = build_summary_row(rec)
        rows.append(row)

    # Step 5: Write clean consolidated CSV
    output_csv = str(config.SUMMARY_CSV_PATH)
    df = write_clean_csv(rows, output_csv)

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
