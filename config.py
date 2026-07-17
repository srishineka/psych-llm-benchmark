"""
Central configuration: default model IDs, provider choices, and log paths.
Edit this file (or override via environment variables) to switch which
backend powers each agent role.

PHASE-IN PLAN (per user request):
    - PATIENT agent  -> start on Gemini or Mistral (free API tiers), switch
      to OpenAI later by changing PATIENT_PROVIDER/PATIENT_MODEL below.
    - THERAPIST agent -> the system under test. Swap freely between Groq
      (Llama-3.1-8b, Mixtral-8x7b), OpenAI (GPT-4 Turbo), or a locally
      hosted model (MentaLLaMA, ChatCounselor) run in Colab.
    - EVALUATOR agent -> keep on a stronger/independent model (Gemini,
      Mistral Large, or OpenAI) so it isn't the same model grading itself.

NOTE ON FREE-TIER LIMITS: Provider free tiers (rate limits, model
availability) change frequently and without notice. Always check the
provider's live docs before running a large batch of sessions:
    - Gemini:  https://ai.google.dev/gemini-api/docs/rate-limits
    - Mistral: https://docs.mistral.ai/deployment/laplateforme/overview/
    - Groq:    https://console.groq.com/docs/models
"""

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Provider / model selection (env vars override these defaults)
# --------------------------------------------------------------------------

PATIENT_PROVIDER = os.getenv("PATIENT_PROVIDER", "gemini")        # gemini | mistral | openai
PATIENT_MODEL = os.getenv("PATIENT_MODEL", "gemini-2.5-flash")

THERAPIST_PROVIDER = os.getenv("THERAPIST_PROVIDER", "groq")      # groq | openai | hf_local | mistral | gemini
THERAPIST_MODEL = os.getenv("THERAPIST_MODEL", "llama-3.1-8b-instant")

EVALUATOR_PROVIDER = os.getenv("EVALUATOR_PROVIDER", "mistral")   # keep independent from therapist provider
EVALUATOR_MODEL = os.getenv("EVALUATOR_MODEL", "mistral-large-latest")

# --------------------------------------------------------------------------
# API keys (loaded from environment / .env — never hardcode keys here)
# --------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --------------------------------------------------------------------------
# Conversation settings
# --------------------------------------------------------------------------

MAX_TURNS = int(os.getenv("MAX_TURNS", "10"))
ALL_CONDITIONS = [
    "GAD", "OCD", "MDD", "Bipolar", "BPD",
    "ADHD", "Addiction", "ASD", "Schizophrenia",
]

# --------------------------------------------------------------------------
# Structured log storage
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
TRANSCRIPTS_DIR = LOGS_DIR / "transcripts"     # one raw JSON per session (full dialogue)
EVALUATIONS_DIR = LOGS_DIR / "evaluations"     # one JSON per session (evaluator scoring output)
SUMMARY_DIR = LOGS_DIR / "summary"             # aggregated CSV + rollups
FIGURES_DIR = SUMMARY_DIR / "figures"          # exported PNG charts
WHY_REPORTS_DIR = SUMMARY_DIR / "why_reports"  # per-model qualitative "why" narratives
SUMMARY_CSV_PATH = SUMMARY_DIR / "summary_metrics.csv"

for _dir in (TRANSCRIPTS_DIR, EVALUATIONS_DIR, SUMMARY_DIR, FIGURES_DIR, WHY_REPORTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
