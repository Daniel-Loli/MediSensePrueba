# app/agents/nodes.py
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
    
    # 1. RAG: Buscar contexto clínico
    context = knowledge_base.search(user_msg)
    history_str = "\n".join(state.get("history", [])[-4:])
    
    # 2. Lógica de Negocio: ¿Debemos crear un caso/cita?
    # Eliminamos la restricción de len > 20 y mejoramos la detección
    case_id = None
    system_status = "No se ha realizado ninguna acción administrativa."
    
    keywords_cita = ["cita", "agendar", "registrar", "atenderme", "turno", "médico"]
    keywords_sintomas = ["dolor", "fiebre", "gripe", "malestar", "siento"]
    
    # Detectar intención de cita o reporte de síntomas fuertes
    has_intent_cita = any(k in user_msg.lower() for k in keywords_cita)
    has_sintomas = any(k in user_msg.lower() for k in keywords_sintomas)

    if has_intent_cita or (has_sintomas and len(user_msg) > 10):
        try:
            # Extraer datos estructurados
            diag_resp = llm.invoke([HumanMessage(content=DIAGNOSIS_EXTRACTION_PROMPT.format(text=user_msg))])
            clean = diag_resp.content.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            
            # Crear payload
            payload = {
                "patient": state["patient_data"],
                "conversation_summary": user_msg,
                "symptoms": [user_msg],
                "specialty": data.get("specialty", "Medicina General"),
                "risk_level": data.get("risk_level", "BAJO"),
                "possible_diagnosis": data.get("possible_diagnosis", "Evaluación pendiente"),
                "recommended_treatment": data.get("recommended_treatment", "Reposo"),
                "diagnosis_justification": data.get("justification", ""),
                "appointment_time": "2024-12-01 09:00:00" 
            }
            
            # Llamada a la API
            res = business_client.create_medical_case(payload)
            
            if res:
                case_id = res.get("case", {}).get("id")
                # AQUÍ está la clave: Le contamos al Prompt que ya hicimos el trabajo
                system_status = f"✅ ÉXITO: Se ha registrado un pre-ingreso médico con ID de caso #{case_id}. La IA debe confirmar esto al usuario."
            else:
                system_status = "⚠️ ERROR: Se intentó registrar la cita pero el sistema backend no respondió. Pedir al usuario que llame por teléfono."
                
        except Exception as e:
            print(f"Error creando caso: {e}")
            system_status = "Error interno intentando procesar la solicitud."

    # 3. Generar respuesta FINAL de la IA (ahora con toda la info)
    prompt = MEDICAL_RAG_PROMPT.format(
        context=context, 
        history=history_str, 
        system_status=system_status, # <--- Variable nueva inyectada
        question=user_msg
    )
    
    resp = llm.invoke([HumanMessage(content=prompt)])
    ai_text = resp.content
    
    return {**state, "ai_response": ai_text, "case_id": case_id}