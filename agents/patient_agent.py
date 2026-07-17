"""
Phase 1: Patient Simulation Engine
"""

from dataclasses import dataclass, field
from typing import List, Dict

from .llm_clients import LLMClient
from prompts.patient_profiles import (
    HiddenDiagnosticProfile,
    PATIENT_PROFILES,
    build_patient_system_prompt,
)


@dataclass
class PatientAgent:
    profile: HiddenDiagnosticProfile
    llm: LLMClient
    behavioral_manifestation: str
    few_shot_examples: str
    system_prompt: str = field(init=False)

    def __post_init__(self):
        self.system_prompt = build_patient_system_prompt(
            self.profile, self.behavioral_manifestation, self.few_shot_examples
        )

    def respond(self, transcript: List[Dict[str, str]]) -> str:
        """transcript is from the patient's POV: therapist turns are 'user', patient's own prior turns are 'assistant'."""
        return self.llm.chat(self.system_prompt, transcript)

    @classmethod
    def from_condition(cls, condition: str, llm: LLMClient) -> "PatientAgent":
        """Convenience constructor: PatientAgent.from_condition('BPD', llm)."""
        if condition not in PATIENT_PROFILES:
            raise ValueError(
                f"Unknown condition '{condition}'. Available: {list(PATIENT_PROFILES.keys())}"
            )
        profile, behavioral, few_shot = PATIENT_PROFILES[condition]
        return cls(profile=profile, llm=llm, behavioral_manifestation=behavioral, few_shot_examples=few_shot)
