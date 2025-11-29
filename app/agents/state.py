from typing import TypedDict, List, Optional, Dict, Any

# total=False para que los campos sean opcionales a nivel de type-checking
class AgentState(TypedDict, total=False):
    # Datos básicos de sesión
    whatsapp_number: str
    user_message: str

    # Identificación
    dni: Optional[str]
    patient_data: Optional[dict]
    is_verified: bool
    verification_step: str       # "ask_dni" | "ask_code" | "verified"
    just_verified: bool          # True solo en el turno en que se validó el código

    # Intención general (para usos futuros)
    intent: str

    # Flujo actual
    flow: Optional[str]          # "menu" | "appointment" | "wellness" | "medical"
    menu_step: Optional[str]

    # Flujo de cita
    appointment_step: Optional[str]      # "ask_specialty" | "ask_reason" | "choose_slot" | "confirm"
    appointment_data: Optional[Dict[str, Any]]
    appointment_slots: Optional[List[Dict[str, Any]]]

    # Historial y respuesta
    history: List[str]
    ai_response: str
    case_id: Optional[int]
