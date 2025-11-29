import json
from langchain_core.messages import HumanMessage
from app.core.llm import llm
from app.core.business import business_client
from app.core.knowledge import knowledge_base
from app.agents.state import AgentState
from app.agents.prompts import (
    TRIAGE_PROMPT,
    MEDICAL_RAG_PROMPT,
    DIAGNOSIS_EXTRACTION_PROMPT,
    WELLNESS_PROMPT,
)

# ==========================================================
# MAPEO DE ESPECIALIDADES → NOMBRES EXACTOS EN LA BD
# ==========================================================

SPECIALTY_MAP = {
    # Medicina general
    "general": "Medicina General",
    "medicina general": "Medicina General",
    "medicina": "Medicina General",
    "consulta general": "Medicina General",

    # Nutrición
    "nutricion": "Nutricion",
    "nutrición": "Nutricion",

    # Dermatología
    "dermatologia": "Dermatología",
    "dermatología": "Dermatología",

    # Oftalmología
    "oftalmologia": "Oftalmología",
    "oftalmología": "Oftalmología",

    # Ginecología
    "ginecologia": "Ginecología",
    "ginecología": "Ginecología",

    # Cirugía plástica
    "cirugia plastica": "Cirugía plástica",
    "cirugía plástica": "Cirugía plástica",

    # Traumatología
    "traumatologia": "Traumatología",
    "traumatología": "Traumatología",

    # Neumología
    "neumologia": "Neumología",
    "neumología": "Neumología",

    # Cardiología
    "cardiologia": "Cardiología",
    "cardiología": "Cardiología",

    # Psicología
    "psicologia": "Psicología",
    "psicología": "Psicología",

    # Odontología
    "odontologia": "Odontología",
    "odontología": "Odontología",

    # Fisioterapia
    "fisioterapia": "Fisioterapia",

    # Obstetricia
    "obstetricia": "Obstetricia",
}


def normalize_specialty(raw: str | None) -> str:
    """
    Normaliza el texto de especialidad que devuelve el LLM
    a un valor EXACTO existente en la tabla users.specialty.
    Si no se reconoce, devuelve 'Medicina General' por defecto.
    """
    if not raw:
        return "Medicina General"
    key = raw.strip().lower()
    return SPECIALTY_MAP.get(key, "Medicina General")


# ==========================================================
# NODOS DEL AGENTE
# ==========================================================

def verification_node(state: AgentState) -> AgentState:
    msg = state["user_message"].strip()
    step = state.get("verification_step", "ask_dni")
    
    # Lógica de verificación
    if step == "ask_dni":
        if msg.isdigit() and len(msg) >= 8:
            exists = business_client.get_patient_by_dni(msg)
            if exists and exists.get("exists"):
                business_client.send_verification_code(msg)
                return {
                    **state,
                    "dni": msg,
                    "verification_step": "ask_code",
                    "ai_response": (
                        f"Hola {exists['patient']['full_name']}. "
                        "Te envié un código al correo. Por favor escríbelo."
                    ),
                }
            return {
                **state,
                "ai_response": "Ese DNI no está registrado. Por favor contacta a administración.",
            }
        return {
            **state,
            "ai_response": "Hola, soy la IA de MediSense. Por favor ingresa tu DNI para atenderte.",
        }

    elif step == "ask_code":
        patient = business_client.verify_code(state["dni"], msg)
        if patient:
            return {
                **state,
                "is_verified": True,
                "patient_data": patient,
                "verification_step": "verified",
                "ai_response": "Identidad verificada. ¿En qué puedo ayudarte hoy? (Tengo consulta médica o tips de bienestar)",
            }
        return {**state, "ai_response": "Código incorrecto. Inténtalo nuevamente."}
            
    return state


def triage_node(state: AgentState) -> AgentState:
    # Clasificar intención
    resp = llm.invoke([
        HumanMessage(content=TRIAGE_PROMPT.format(message=state["user_message"]))
    ])
    intent_raw = resp.content.strip().upper()
    final_intent = (
        "medical" if "MEDICAL" in intent_raw
        else "wellness" if "WELLNESS" in intent_raw
        else "general"
    )
    return {**state, "intent": final_intent}


def wellness_node(state: AgentState) -> AgentState:
    resp = llm.invoke([
        HumanMessage(content=WELLNESS_PROMPT.format(message=state["user_message"]))
    ])
    business_client.log_wellness(
        state["patient_data"],
        state["user_message"],
        resp.content,
    )
    return {**state, "ai_response": resp.content}


def medical_node(state: AgentState) -> AgentState:
    user_msg = state["user_message"]
    text_lower = user_msg.lower()
    
    # 1. RAG: Buscar contexto clínico
    context = knowledge_base.search(user_msg)
    history_str = "\n".join(state.get("history", [])[-4:])
    
    # 2. Lógica de Negocio: ¿Debemos crear un caso/cita?
    case_id = None
    system_status = "No se ha realizado ninguna acción administrativa."
    
    keywords_cita = ["cita", "agendar", "registrar", "atenderme", "turno", "médico"]
    keywords_sintomas = ["dolor", "fiebre", "gripe", "malestar", "siento"]
    
    has_intent_cita = any(k in text_lower for k in keywords_cita)
    has_sintomas = any(k in text_lower for k in keywords_sintomas)

    if has_intent_cita or (has_sintomas and len(user_msg) > 10):
        try:
            # Extraer datos estructurados desde el LLM
            diag_resp = llm.invoke([
                HumanMessage(
                    content=DIAGNOSIS_EXTRACTION_PROMPT.format(text=user_msg)
                )
            ])
            clean = (
                diag_resp.content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            data = {}
            try:
                data = json.loads(clean)
            except Exception as e:
                print(f"❌ Error parseando JSON de diagnóstico: {e} | raw={clean}")
                data = {}

            # Normalizar especialidad a un valor existente en la BD
            raw_specialty = data.get("specialty")
            normalized_specialty = normalize_specialty(raw_specialty)

            # Crear payload
            payload = {
                "patient": state["patient_data"],
                "conversation_summary": user_msg,
                "symptoms": [user_msg],
                "specialty": normalized_specialty,
                "risk_level": data.get("risk_level", "BAJO"),
                "possible_diagnosis": data.get(
                    "possible_diagnosis", "Evaluación pendiente"
                ),
                "recommended_treatment": data.get(
                    "recommended_treatment", "Reposo"
                ),
                "diagnosis_justification": data.get("justification", ""),
                # Luego lo harás dinámico, de momento hardcode
                "appointment_time": "2024-12-01 09:00:00",
            }
            
            # Llamada a la API de negocio
            res = business_client.create_medical_case(payload)
            
            if res:
                case_id = res.get("case", {}).get("id")
                system_status = (
                    f"✅ ÉXITO: Se ha registrado un pre-ingreso médico con ID de caso "
                    f"#{case_id}. La IA debe confirmar esto al usuario."
                )
            else:
                system_status = (
                    "⚠️ ERROR: Se intentó registrar la cita pero el sistema backend "
                    "no respondió o devolvió error. Pedir al usuario que llame por teléfono."
                )
                
        except Exception as e:
            print(f"Error creando caso: {e}")
            system_status = "Error interno intentando procesar la solicitud."

    # 3. Generar respuesta FINAL de la IA (con estado del sistema)
    prompt = MEDICAL_RAG_PROMPT.format(
        context=context, 
        history=history_str, 
        system_status=system_status,
        question=user_msg,
    )
    
    resp = llm.invoke([HumanMessage(content=prompt)])
    ai_text = resp.content
    
    return {**state, "ai_response": ai_text, "case_id": case_id}
