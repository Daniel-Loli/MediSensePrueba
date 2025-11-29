import json
from langchain_core.messages import HumanMessage
from app.core.llm import llm
from app.core.business import business_client
from app.core.knowledge import knowledge_base
from app.agents.state import AgentState
from app.agents.prompts import *

def verification_node(state: AgentState) -> AgentState:
    msg = state["user_message"].strip()
    step = state.get("verification_step", "ask_dni")
    
    # Lógica de verificación
    if step == "ask_dni":
        if msg.isdigit() and len(msg) >= 8:
            exists = business_client.get_patient_by_dni(msg)
            if exists and exists.get("exists"):
                business_client.send_verification_code(msg)
                return {**state, "dni": msg, "verification_step": "ask_code", 
                        "ai_response": f"Hola {exists['patient']['full_name']}. Te envié un código al correo. Por favor escríbelo."}
            return {**state, "ai_response": "Ese DNI no está registrado. Por favor contacta a administración."}
        return {**state, "ai_response": "Hola, soy la IA de MediSense. Por favor ingresa tu DNI para atenderte."}

    elif step == "ask_code":
        patient = business_client.verify_code(state["dni"], msg)
        if patient:
            return {**state, "is_verified": True, "patient_data": patient, "verification_step": "verified",
                    "ai_response": "Identidad verificada. ¿En qué puedo ayudarte hoy? (Tengo consulta médica o tips de bienestar)"}
        return {**state, "ai_response": "Código incorrecto. Inténtalo nuevamente."}
            
    return state

def triage_node(state: AgentState) -> AgentState:
    # Clasificar intención
    resp = llm.invoke([HumanMessage(content=TRIAGE_PROMPT.format(message=state["user_message"]))])
    intent = resp.content.strip().upper()
    final_intent = "medical" if "MEDICAL" in intent else "wellness" if "WELLNESS" in intent else "general"
    return {**state, "intent": final_intent}

def wellness_node(state: AgentState) -> AgentState:
    resp = llm.invoke([HumanMessage(content=WELLNESS_PROMPT.format(message=state["user_message"]))])
    business_client.log_wellness(state["patient_data"], state["user_message"], resp.content)
    return {**state, "ai_response": resp.content}

def medical_node(state: AgentState) -> AgentState:
    user_msg = state["user_message"]
    
    # 1. RAG: Buscar en tu índice existente
    context = knowledge_base.search(user_msg)
    history_str = "\n".join(state.get("history", [])[-4:])
    
    # 2. Generar respuesta
    prompt = MEDICAL_RAG_PROMPT.format(context=context, history=history_str, question=user_msg)
    resp = llm.invoke([HumanMessage(content=prompt)])
    ai_text = resp.content
    
    # 3. Detectar si crear caso (simple heurística)
    case_id = None
    if len(user_msg) > 20 and ("dolor" in user_msg or "cita" in user_msg):
        try:
            diag_resp = llm.invoke([HumanMessage(content=DIAGNOSIS_EXTRACTION_PROMPT.format(text=user_msg))])
            clean = diag_resp.content.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            
            # Crear caso en Node
            payload = {
                "patient": state["patient_data"],
                "conversation_summary": user_msg,
                "symptoms": [user_msg],
                "specialty": data.get("specialty", "General"),
                "risk_level": data.get("risk_level", "BAJO"),
                "possible_diagnosis": data.get("possible_diagnosis"),
                "recommended_treatment": data.get("recommended_treatment"),
                "diagnosis_justification": data.get("justification"),
                "appointment_time": "2024-12-01 09:00:00" # Placeholder
            }
            res = business_client.create_medical_case(payload)
            if res:
                case_id = res.get("case", {}).get("id")
                ai_text += "\n\n[SISTEMA]: He generado un pre-ingreso clínico para evaluación médica."
        except Exception as e:
            print(f"Error creando caso: {e}")

    return {**state, "ai_response": ai_text, "case_id": case_id}