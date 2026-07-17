"""
Phase 2: Conversational Loop Controller

Orchestrates N therapist<->patient exchanges. Neither agent ever sees the
other's system prompt or breaks character — each only receives its own
role-relative view of the transcript (see SessionTranscript.as_*_view()).
"""

from typing import Optional

from agents.patient_agent import PatientAgent
from agents.therapist_agent import TherapistAgent
from .session_transcript import SessionTranscript


class ConversationLoopController:
    def __init__(self, patient: PatientAgent, therapist: TherapistAgent,
                 max_turns: int = 10, opening_line: Optional[str] = None):
        self.patient = patient
        self.therapist = therapist
        self.max_turns = max_turns
        self.opening_line = opening_line or (
            "Hi, thanks for coming in today. What's been going on for you lately?"
        )

    def run(self, condition: str, therapist_model_name: str, patient_model_name: str) -> SessionTranscript:
        transcript = SessionTranscript(
            session_id=SessionTranscript.new_id(),
            condition=condition,
            therapist_model=therapist_model_name,
            patient_model=patient_model_name,
        )

        # Therapist opens the session
        transcript.add_turn("therapist", self.opening_line)

        for _ in range(self.max_turns):
            patient_reply = self.patient.respond(transcript.as_patient_view())
            transcript.add_turn("patient", patient_reply)

            therapist_reply = self.therapist.respond(transcript.as_therapist_view())
            transcript.add_turn("therapist", therapist_reply)

        return transcript
