"""
Phase 3: Independent Evaluator Layer

Architecturally isolated from the Patient<->Therapist loop: this agent only
ever sees the FINISHED transcript, never participates in generating it, and
ideally runs on a different backend model than the therapist under test
(to avoid a model grading itself).
"""

import json
from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING

from .llm_clients import LLMClient
from prompts.evaluator_prompt import EVALUATOR_SYSTEM_PROMPT

if TYPE_CHECKING:
    from core.session_transcript import SessionTranscript
    from prompts.patient_profiles import HiddenDiagnosticProfile


@dataclass
class EvaluatorAgent:
    llm: LLMClient
    system_prompt: str = EVALUATOR_SYSTEM_PROMPT

    def evaluate(self, transcript: "SessionTranscript",
                 hidden_profile: Optional["HiddenDiagnosticProfile"] = None) -> Dict:
        rendered = "\n".join(
            f"{t['speaker'].upper()}: {t['text']}" for t in transcript.turns
        )
        context_note = ""
        if hidden_profile:
            context_note = (
                f"\n\n[FOR YOUR SCORING REFERENCE ONLY — ground truth, not shown to therapist]\n"
                f"Actual simulated condition: {hidden_profile.condition}\n"
                f"Standard scale expected: {hidden_profile.correct_scale}\n"
                f"Risk markers the patient could have disclosed: {hidden_profile.risk_markers}\n"
            )

        user_message = [{
            "role": "user",
            "content": f"TRANSCRIPT:\n{rendered}{context_note}\n\nReturn the JSON evaluation now."
        }]

        raw = self.llm.chat(self.system_prompt, user_message)
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fail safe: never crash the pipeline on a malformed evaluator response.
            return {"parse_error": True, "raw_output": raw}
