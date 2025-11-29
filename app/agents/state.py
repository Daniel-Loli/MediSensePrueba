# app/agents/state.py
from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    whatsapp_number: str
    user_message: str
    dni: Optional[str]
    patient_data: Optional[dict]
    is_verified: bool
    verification_step: str
    intent: str
    history: List[str]
    ai_response: str
    case_id: Optional[int]