"""
Re-evaluates existing transcripts in logs/transcripts/ using the current Evaluator prompt.
Saves updated outputs to logs/evaluations/ and updates summary metrics.

Usage:
    python re_evaluate_transcripts.py --evaluator-provider groq --evaluator-model llama-3.3-70b-versatile
"""

import os
import sys
import glob
import json
import argparse

# Add root project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from agents.llm_clients import get_client
from agents.evaluator_agent import EvaluatorAgent
from core.session_transcript import SessionTranscript
from prompts.patient_profiles import PATIENT_PROFILES
from analytics.exporter import AnalyticsExporter


def main():
    parser = argparse.ArgumentParser(description="Re-run evaluation phase only.")
    parser.add_argument("--evaluator-provider", default=config.EVALUATOR_PROVIDER)
    parser.add_argument("--evaluator-model", default=config.EVALUATOR_MODEL)
    args = parser.parse_args()

    # Load Evaluator LLM client
    evaluator_llm = get_client(args.evaluator_provider, args.evaluator_model)
    evaluator = EvaluatorAgent(llm=evaluator_llm)
    exporter = AnalyticsExporter()

    # Find all transcripts
    transcript_files = glob.glob(os.path.join(str(config.TRANSCRIPTS_DIR), "*.json"))
    if not transcript_files:
        print(f"No transcripts found in {config.TRANSCRIPTS_DIR}")
        return

    print(f"Found {len(transcript_files)} transcripts to re-evaluate.")
    print(f"Using Evaluator: {args.evaluator_provider}/{args.evaluator_model}")

    for idx, fp in enumerate(transcript_files, 1):
        if ".gitkeep" in fp:
            continue

        base_name = os.path.basename(fp)
        print(f"[{idx}/{len(transcript_files)}] Re-evaluating {base_name}...")

        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Create SessionTranscript
        transcript = SessionTranscript(
            session_id=data["session_id"],
            condition=data["condition"],
            therapist_model=data["therapist_model"],
            patient_model=data["patient_model"],
            turns=data["turns"],
            timestamp=data["timestamp"]
        )

        # Load profile
        profile, _, _ = PATIENT_PROFILES[transcript.condition]

        # Run evaluation
        try:
            evaluation = evaluator.evaluate(transcript, hidden_profile=profile)
            
            # Export evaluation JSON to logs/evaluations/
            # Keep the same filename style as existing evaluations
            eval_path = os.path.join(str(config.EVALUATIONS_DIR), base_name)
            with open(eval_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": transcript.session_id,
                    "condition": transcript.condition,
                    "therapist_model": transcript.therapist_model,
                    "patient_model": transcript.patient_model,
                    "timestamp": transcript.timestamp,
                    "evaluation": evaluation,
                }, f, indent=2)

            # Update the summary row in summary_metrics.csv
            exporter.append_summary_row(transcript, evaluation)
            print(f"  -> Successfully re-evaluated and saved to {eval_path}")

        except Exception as e:
            print(f"  -> ERROR re-evaluating {base_name}: {e}")

    # Regenerate charts
    print("\nRe-evaluation finished. Running consolidation script to update summary and figures...")
    try:
        import subprocess
        subprocess.run([sys.executable, "consolidate_logs.py"], check=True)
    except Exception as e:
        print(f"Could not run consolidate_logs.py automatically: {e}")


if __name__ == "__main__":
    main()
