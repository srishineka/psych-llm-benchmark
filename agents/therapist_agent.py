"""
Therapist Agent — the system under test (foundational or domain-specific model).
"""

from dataclasses import dataclass
from typing import List, Dict

from .llm_clients import LLMClient
from prompts.therapist_prompt import THERAPIST_SYSTEM_PROMPT


@dataclass
class TherapistAgent:
    llm: LLMClient
    system_prompt: str = THERAPIST_SYSTEM_PROMPT

    def respond(self, transcript: List[Dict[str, str]]) -> str:
        """transcript is from the therapist's POV: patient turns are 'user', therapist's own prior turns are 'assistant'."""
        return self.llm.chat(self.system_prompt, transcript)
