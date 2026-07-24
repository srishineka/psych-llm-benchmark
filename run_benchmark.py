"""
Main orchestration entrypoint.

Examples
--------
Run all 9 conditions against one therapist model (Groq's free Llama-3.1-8b),
patient on Gemini's free tier, evaluator on Mistral:

    python run_benchmark.py --conditions all --therapist-provider groq \\
        --therapist-model llama-3.1-8b-instant

Run a single condition against multiple therapist models in one pass, then
build the comparison dashboard + qualitative "why" reports:

    python run_benchmark.py --conditions BPD Schizophrenia \\
        --therapist-provider groq --therapist-model llama-3.1-8b-instant
    python run_benchmark.py --conditions BPD Schizophrenia \\
        --therapist-provider groq --therapist-model mixtral-8x7b-32768
    python run_benchmark.py --analyze-only

(Re-running with a different --therapist-model appends new rows to the same
summary CSV, so the dashboard/why-reports naturally compare across models
once you've run each one you care about.)
"""

import argparse
import sys
from typing import Optional

import config
from agents.llm_clients import get_client
from agents.patient_agent import PatientAgent
from agents.therapist_agent import TherapistAgent
from agents.evaluator_agent import EvaluatorAgent
from core.loop_controller import ConversationLoopController
from analytics.exporter import AnalyticsExporter
from analytics.aggregator import load_all_evaluations, load_full_records
from analytics.visualize import generate_all_charts
from analytics.why_analysis import WhyAnalyzer
from prompts.patient_profiles import PATIENT_PROFILES


def run_single_session(condition: str,
                        patient_llm, therapist_llm, evaluator_llm,
                        max_turns: int, exporter: AnalyticsExporter,
                        therapist_system_prompt: Optional[str] = None):
    profile, _, _ = PATIENT_PROFILES[condition]

    patient = PatientAgent.from_condition(condition, patient_llm)
    if therapist_system_prompt:
        therapist = TherapistAgent(llm=therapist_llm, system_prompt=therapist_system_prompt)
    else:
        therapist = TherapistAgent(llm=therapist_llm)
    evaluator = EvaluatorAgent(llm=evaluator_llm)

    controller = ConversationLoopController(patient, therapist, max_turns=max_turns)
    transcript = controller.run(
        condition=condition,
        therapist_model_name=therapist_llm.model_name,
        patient_model_name=patient_llm.model_name,
    )

    evaluation = evaluator.evaluate(transcript, hidden_profile=profile)
    paths = exporter.export_all(transcript, evaluation, evaluator_model=evaluator_llm.model_name)

    print(f"  [{condition}] overall_score={evaluation.get('overall_score_0_to_100')} "
          f"-> {paths['transcript_path']}")
    return transcript, evaluation


def main():
    parser = argparse.ArgumentParser(description="Run the psychiatric LLM benchmark.")
    parser.add_argument("--conditions", nargs="+", default=["all"],
                         help="Condition names (GAD OCD MDD Bipolar BPD ADHD Addiction ASD Schizophrenia) or 'all'.")
    parser.add_argument("--patient-provider", default=config.PATIENT_PROVIDER)
    parser.add_argument("--patient-model", default=config.PATIENT_MODEL)
    parser.add_argument("--therapist-provider", default=config.THERAPIST_PROVIDER)
    parser.add_argument("--therapist-model", default=config.THERAPIST_MODEL)
    parser.add_argument("--evaluator-provider", default=config.EVALUATOR_PROVIDER)
    parser.add_argument("--evaluator-model", default=config.EVALUATOR_MODEL)
    parser.add_argument("--max-turns", type=int, default=config.MAX_TURNS)
    parser.add_argument("--therapist-system-prompt", default=None,
                         help="Custom system prompt for the therapist agent.")
    parser.add_argument("--analyze-only", action="store_true",
                         help="Skip running sessions; just regenerate charts + why-reports from existing logs.")
    args = parser.parse_args()

    exporter = AnalyticsExporter()

    if not args.analyze_only:
        conditions = list(PATIENT_PROFILES.keys()) if args.conditions == ["all"] else args.conditions
        unknown = [c for c in conditions if c not in PATIENT_PROFILES]
        if unknown:
            print(f"Unknown condition(s): {unknown}. Available: {list(PATIENT_PROFILES.keys())}")
            sys.exit(1)

        patient_llm = get_client(args.patient_provider, args.patient_model)
        therapist_llm = get_client(args.therapist_provider, args.therapist_model)
        evaluator_llm = get_client(args.evaluator_provider, args.evaluator_model)

        print(f"Running {len(conditions)} condition(s) | "
              f"patient={args.patient_provider}/{args.patient_model} | "
              f"therapist={args.therapist_provider}/{args.therapist_model} | "
              f"evaluator={args.evaluator_provider}/{args.evaluator_model}")

        for condition in conditions:
            run_single_session(condition, patient_llm, therapist_llm, evaluator_llm,
                                args.max_turns, exporter,
                                therapist_system_prompt=args.therapist_system_prompt)

    # ---- Phase 4: analytics dashboard + qualitative "why" synthesis ----
    print("\nBuilding analytics...")
    df = load_all_evaluations()
    chart_paths = generate_all_charts(df)
    for name, path in chart_paths.items():
        print(f"  chart: {name} -> {path}")

    print(f"\nGenerating qualitative 'why' reports for {args.therapist_model}...")
    records = load_full_records()
    # Filter to only the model being run so we don't waste LLM tokens regenerating other models
    records = [r for r in records if r["therapist_model"] == args.therapist_model]
    
    if records:
        evaluator_llm_for_why = get_client(args.evaluator_provider, args.evaluator_model)
        why_analyzer = WhyAnalyzer(llm=evaluator_llm_for_why)
        report_paths = why_analyzer.analyze_all(records)
        for model_name, path in report_paths.items():
            print(f"  why-report: {model_name} -> {path}")
    else:
        print(f"  No records found for {args.therapist_model} to generate a why-report.")


if __name__ == "__main__":
    main()
