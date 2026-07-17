import datetime
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Literal


@dataclass
class SessionTranscript:
    session_id: str
    condition: str
    therapist_model: str
    patient_model: str
    turns: List[Dict[str, str]] = field(default_factory=list)  # [{"speaker": "therapist"|"patient", "text": str}]
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    def add_turn(self, speaker: Literal["therapist", "patient"], text: str):
        self.turns.append({"speaker": speaker, "text": text})

    def as_therapist_view(self) -> List[Dict[str, str]]:
        """From the therapist's POV: patient turns are 'user', therapist's own turns are 'assistant'."""
        return [
            {"role": "assistant" if t["speaker"] == "therapist" else "user", "content": t["text"]}
            for t in self.turns
        ]

    def as_patient_view(self) -> List[Dict[str, str]]:
        """From the patient's POV: therapist turns are 'user', patient's own turns are 'assistant'."""
        return [
            {"role": "assistant" if t["speaker"] == "patient" else "user", "content": t["text"]}
            for t in self.turns
        ]

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
