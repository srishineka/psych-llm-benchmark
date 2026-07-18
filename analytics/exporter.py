"""
Phase 4: Analytics Engine — structured log export.

Storage layout (see config.py):
    logs/
      transcripts/<session_id>.json   -> full raw dialogue (patient <-> therapist)
      evaluations/<session_id>.json   -> evaluator's scoring output for that session
      summary/
        summary_metrics.csv           -> one row per session, flattened metrics
        figures/                      -> PNG charts from analytics/visualize.py
        why_reports/                  -> qualitative "why" narratives per model
"""

import csv
import json
import os
from typing import Dict

import config
from core.session_transcript import SessionTranscript
from .metrics import compute_formula_metrics


class AnalyticsExporter:
    def __init__(self,
                 transcripts_dir=None, evaluations_dir=None, summary_csv_path=None):
        self.transcripts_dir = transcripts_dir or config.TRANSCRIPTS_DIR
        self.evaluations_dir = evaluations_dir or config.EVALUATIONS_DIR
        self.summary_csv_path = summary_csv_path or config.SUMMARY_CSV_PATH

    def export_transcript(self, transcript: SessionTranscript) -> str:
        path = os.path.join(self.transcripts_dir, f"{transcript.session_id}.json")
        with open(path, "w") as f:
            json.dump({
                "session_id": transcript.session_id,
                "condition": transcript.condition,
                "therapist_model": transcript.therapist_model,
                "patient_model": transcript.patient_model,
                "timestamp": transcript.timestamp,
                "turns": transcript.turns,
            }, f, indent=2)
        return path

    def export_evaluation(self, transcript: SessionTranscript, evaluation: Dict) -> str:
        path = os.path.join(self.evaluations_dir, f"{transcript.session_id}.json")
        with open(path, "w") as f:
            json.dump({
                "session_id": transcript.session_id,
                "condition": transcript.condition,
                "therapist_model": transcript.therapist_model,
                "patient_model": transcript.patient_model,
                "timestamp": transcript.timestamp,
                "evaluation": evaluation,
            }, f, indent=2)
        return path

    def append_summary_row(self, transcript: SessionTranscript, evaluation: Dict) -> str:
        file_exists = os.path.isfile(self.summary_csv_path)

        diag = evaluation.get("diagnostic_scoring_accuracy", {})
        safety = evaluation.get("safety_red_line_adherence", {})
        coherence = evaluation.get("conversational_coherence", {})
        empathy = evaluation.get("empathy_alignment_and_bias", {})
        bl = empathy.get("barrett_lennard_dimensions", {})

        # LLM's own holistic judgments (score_0_to_10 fields the Evaluator assigned directly)
        row = {
            "session_id": transcript.session_id,
            "condition": transcript.condition,
            "therapist_model": transcript.therapist_model,
            "patient_model": transcript.patient_model,
            "timestamp": transcript.timestamp,
            "llm_diagnostic_score": diag.get("score_0_to_10"),
            "llm_safety_score": safety.get("score_0_to_10"),
            "llm_coherence_score": coherence.get("score_0_to_10"),
            "llm_empathy_score": empathy.get("score_0_to_10"),
            "bl_level_of_regard": bl.get("level_of_regard"),
            "bl_empathic_understanding": bl.get("empathic_understanding"),
            "bl_unconditionality_of_regard": bl.get("unconditionality_of_regard"),
            "bl_congruence": bl.get("congruence"),
            "llm_overall_score": evaluation.get("overall_score_0_to_100"),
            "missed_risk_markers_count": len(safety.get("missed_risk_markers", [])),
            "hallucinations_count": len(safety.get("hallucinated_clinical_claims", [])),
            "bias_flags_count": len(empathy.get("western_centric_bias_flags", [])),
        }

        # Formula-derived metrics computed independently from the same
        # structured flags (see analytics/metrics.py + README "Formula
        # Reference") — sit side by side with the LLM's holistic scores
        # above so a paper can report agreement/disagreement between them.
        formula = compute_formula_metrics(transcript.condition, transcript.turns, evaluation)
        row.update(formula.as_dict())

        with open(self.summary_csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        return self.summary_csv_path

    def export_all(self, transcript: SessionTranscript, evaluation: Dict) -> Dict[str, str]:
        return {
            "transcript_path": self.export_transcript(transcript),
            "evaluation_path": self.export_evaluation(transcript, evaluation),
            "summary_csv_path": self.append_summary_row(transcript, evaluation),
        }
