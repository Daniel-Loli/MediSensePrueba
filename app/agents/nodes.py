# app/agents/nodes.py

import json
from datetime import datetime, timedelta
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
# CONSTANTES / TEXTOS AMIGABLES
# ==========================================================

MENU_TEXT = (
    "¡Genial! Hemos verificado tu identidad correctamente ✅.\n\n"
    "Estoy aquí para ayudarte con tu salud. ¿Qué te gustaría hacer hoy? "
    "(Responde solo con el número de la opción):\n\n"
    "1️⃣ Agendar una cita médica\n"
    "2️⃣ Recibir consejos de nutrición y bienestar\n"
    "3️⃣ Información sobre temas de salud"
)

# ... (MANTENER APPOINTMENT_SPECIALTIES y SPECIALTY_MAP IGUAL QUE ANTES) ...
# ... (Son diccionarios de lógica interna, no necesitan cambios de texto) ...
APPOINTMENT_SPECIALTIES = {
    "1": "Medicina General",
    "2": "Nutricion",
    "3": "Dermatologia",
    "4": "Oftalmologia",
    "5": "Ginecologia",
    "6": "Cirugia Plastica",
    "7": "Traumatologia",
    "8": "Neumologia",
    "9": "Cardiologia",
    "10": "Psicologia",
    "11": "Odontologia",
    "12": "Fisioterapia",
    "13": "Obstetricia",
}

SPECIALTY_MAP = {
    # ... (MANTENER EL MISMO MAPA QUE YA TIENES) ...
    "general": "Medicina General",
    "medicina general": "Medicina General",
    "medicina": "Medicina General",
    "consulta general": "Medicina General",
    "clinica general": "Medicina General",
    "nutricion": "Nutricion",
    "nutrición": "Nutricion",
    "nutricionista": "Nutricion",
    "dermatologia": "Dermatologia",
    "dermatología": "Dermatologia",
    "piel": "Dermatologia",
    "oftalmologia": "Oftalmologia",
    "oftalmología": "Oftalmologia",
    "ojos": "Oftalmologia",
    "ginecologia": "Ginecologia",
    "ginecología": "Ginecologia",
    "cirugia plastica": "Cirugia Plastica",
    "cirugía plástica": "Cirugia Plastica",
    "traumatologia": "Traumatologia",
    "traumatología": "Traumatologia",
    "neumologia": "Neumologia",
    "neumología": "Neumologia",
    "cardiologia": "Cardiologia",
    "cardiología": "Cardiologia",
    "corazon": "Cardiologia",
    "corazón": "Cardiologia",
    "psicologia": "Psicologia",
    "psicología": "Psicologia",
    "odontologia": "Odontologia",
    "odontología": "Odontologia",
    "dentista": "Odontologia",
    "fisioterapia": "Fisioterapia",
    "terapia fisica": "Fisioterapia",
    "terapia física": "Fisioterapia",
    "obstetricia": "Obstetricia",
    "obstetra": "Obstetricia",
}

def normalize_specialty(raw: str | None) -> str:
    if not raw:
        return "Medicina General"
    key = raw.strip().lower()
    if key in SPECIALTY_MAP:
        return SPECIALTY_MAP[key]
    for pattern, normalized in SPECIALTY_MAP.items():
        if pattern in key:
            return normalized
    return "Medicina General"

# ==========================================================
# NODO 1: VERIFICACIÓN (DNI + CÓDIGO)
# ==========================================================

def verification_node(state: AgentState) -> AgentState:
    msg = state["user_message"].strip()
    step = state.get("verification_step", "ask_dni")
    state = {**state, "just_verified": False}

    # 1) Pedir DNI
    if step == "ask_dni":
        if msg.isdigit() and len(msg) >= 8:
            exists = business_client.get_patient_by_dni(msg)
            if exists and exists.get("exists"):
                business_client.send_verification_code(msg)
                name = exists['patient']['full_name'].split()[0] # Solo primer nombre para ser mas amigable
                return {
                    **state,
                    "dni": msg,
                    "verification_step": "ask_code",
                    "ai_response": (
                        f"¡Hola {name}! 👋 Es un gusto saludarte.\n"
                        "Para proteger tu cuenta, te acabo de enviar un código de verificación a tu correo 📧.\n"
                        "Por favor, escríbelo aquí para continuar."
                    ),
                }
            return {
                **state,
                "ai_response": (
                    "Lo siento, no encuentro ese DNI en mi base de datos 😔.\n"
                    "¿Podrías verificar el número e intentarlo de nuevo? O comunícate con administración si crees que es un error."
                ),
            }

        return {
            **state,
            "ai_response": (
                "¡Hola! Soy el asistente virtual de MediSense 🤖💙.\n"
                "Estoy aquí para ayudarte. Por favor, ingresa tu número de DNI para poder identificarte."
            ),
        }

    # 2) Validar código
    elif step == "ask_code":
        patient = business_client.verify_code(state["dni"], msg)
        if patient:
            return {
                **state,
                "is_verified": True,
                "patient_data": patient,
                "verification_step": "verified",
                "just_verified": True,
                "flow": "menu",
                "appointment_step": None,
                "appointment_data": {},
                "appointment_slots": [],
                "ai_response": MENU_TEXT,
            }
        return {**state, "ai_response": "Mmm... ese código no parece ser el correcto 🤔. Por favor revísalo e inténtalo nuevamente."}

    elif step == "verified":
        return {**state, "just_verified": False}

    return state


# ==========================================================
# NODO 2: MENÚ PRINCIPAL
# ==========================================================

def menu_node(state: AgentState) -> AgentState:
    msg_raw = state["user_message"].strip()
    msg = msg_raw.lower()
    option = None

    if msg in ("1", "2", "3"):
        option = msg
    elif "cita" in msg or "agendar" in msg or "registrar" in msg:
        option = "1"
    elif "nutric" in msg or "consejo" in msg:
        option = "2"
    elif "informacion" in msg or "información" in msg or "tema" in msg:
        option = "3"

    # --- Opción 1: Registrar cita ---
    if option == "1":
        text = (
            "¡Excelente! Vamos a programar tu cita 🗓️.\n\n"
            "Primero, por favor dime **con qué especialidad necesitas atenderte** (escribe el número):\n\n"
            "1. Medicina General\n"
            "2. Nutrición\n"
            "3. Dermatología\n"
            "4. Oftalmología\n"
            "5. Ginecología\n"
            "6. Cirugía plástica\n"
            "7. Traumatología\n"
            "8. Neumología\n"
            "9. Cardiología\n"
            "10. Psicología\n"
            "11. Odontología\n"
            "12. Fisioterapia\n"
            "13. Obstetricia\n\n"
            "✨ *Opción 14: No estoy seguro, prefiero que la IA me recomiende según mis síntomas.*"
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "ask_specialty",
            "appointment_data": {},
            "appointment_slots": [],
            "ai_response": text,
        }

    # --- Opción 2: Tips nutricionales ---
    if option == "2":
        text = (
            "¡Qué buena iniciativa cuidar tu salud! 🍎🥗\n"
            "Cuéntame, ¿qué objetivo te gustaría lograr? (ej: comer más sano, bajar de peso, ganar energía, controlar el colesterol...)."
        )
        return {
            **state,
            "flow": "wellness",
            "ai_response": text,
        }

    # --- Opción 3: Información médica ---
    if option == "3":
        text = (
            "Entendido 📚. Estoy capacitado para responder dudas médicas generales.\n"
            "¿Sobre qué tema o condición te gustaría recibir información hoy? (ej: diabetes, cuidados de la piel, dolor de cabeza...)."
        )
        return {
            **state,
            "flow": "medical",
            "ai_response": text,
        }

    return {
        **state,
        "flow": "menu",
        "ai_response": (
            "Disculpa, no entendí bien tu respuesta 😅.\n" + MENU_TEXT
        ),
    }


# ==========================================================
# NODO 3: WELLNESS (Modificado solo el prompt en prompts.py)
# ==========================================================

def wellness_node(state: AgentState) -> AgentState:
    resp = llm.invoke([
        HumanMessage(content=WELLNESS_PROMPT.format(message=state["user_message"]))
    ])
    business_client.log_wellness(state.get("patient_data"), state["user_message"], resp.content)
    return {**state, "ai_response": resp.content}


# ==========================================================
# NODO 4: MEDICAL (Modificado solo el prompt en prompts.py)
# ==========================================================

def medical_node(state: AgentState) -> AgentState:
    user_msg = state["user_message"]
    context = knowledge_base.search(user_msg)
    history_str = "\n".join(state.get("history", [])[-4:])

    prompt = MEDICAL_RAG_PROMPT.format(
        context=context,
        history=history_str,
        system_status="No se ha realizado ninguna acción administrativa.",
        question=user_msg,
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    return {**state, "ai_response": resp.content}


# ==========================================================
# NODO 5: FLUJO DE CITA
# ==========================================================

def appointment_node(state: AgentState) -> AgentState:
    step = state.get("appointment_step", "ask_specialty")
    msg_raw = state["user_message"].strip()
    msg = msg_raw.lower()
    data = state.get("appointment_data") or {}
    slots = state.get("appointment_slots") or []

    # 5.1 Elegir especialidad
    if step == "ask_specialty":
        specialty = None
        if msg == "14" or "elige" in msg or "sintoma" in msg or "síntoma" in msg:
            data["choose_by_symptoms"] = True
            text = (
                "Entendido, yo te ayudo a elegir. 🤝\n\n"
                "Por favor, **cuéntame brevemente qué síntomas tienes** y desde cuándo.\n"
                "(Por ejemplo: 'Me duele mucho la cabeza y tengo náuseas desde ayer')."
            )
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "ask_reason",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": text,
            }

        if msg in APPOINTMENT_SPECIALTIES:
            specialty = APPOINTMENT_SPECIALTIES[msg]
        else:
            for val in APPOINTMENT_SPECIALTIES.values():
                if val.split()[0].lower() in msg:
                    specialty = val
                    break

        if not specialty:
            text = (
                "Disculpa, no logré identificar esa especialidad 😅.\n"
                "Por favor, intenta escribir solo el **número** de la opción (del 1 al 14)."
            )
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "ask_specialty",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": text,
            }

        data["specialty"] = specialty
        data["choose_by_symptoms"] = False
        text = (
            f"¡Perfecto! Buscaremos cita en **{specialty}** 🩺.\n\n"
            "Para que el doctor esté preparado, cuéntame brevemente: **¿Cuál es el motivo de tu consulta y qué síntomas tienes?**"
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "ask_reason",
            "appointment_data": data,
            "appointment_slots": slots,
            "ai_response": text,
        }

    # 5.2 Capturar motivo
    if step == "ask_reason":
        data["reason"] = msg_raw
        try:
            diag_resp = llm.invoke([
                HumanMessage(content=DIAGNOSIS_EXTRACTION_PROMPT.format(text=msg_raw))
            ])
            clean = diag_resp.content.replace("```json", "").replace("```", "").strip()
            diag = json.loads(clean)
            data["risk_level"] = diag.get("risk_level", "BAJO")
            data["possible_diagnosis"] = diag.get("possible_diagnosis", "Evaluación pendiente")
            data["recommended_treatment"] = diag.get("recommended_treatment", "Reposo")
            data["justification"] = diag.get("justification", "")
            if data.get("choose_by_symptoms"):
                detected = normalize_specialty(diag.get("specialty"))
                data["specialty"] = detected
        except Exception:
            data.setdefault("risk_level", "BAJO")
            data["specialty"] = data.get("specialty") or "Medicina General"

        specialty = data.get("specialty")
        base_day = datetime.now() + timedelta(days=1)
        base_day = base_day.replace(minute=0, second=0, microsecond=0)
        new_slots = []
        for hour in [9, 10, 11]:
            start = base_day.replace(hour=hour)
            end = start + timedelta(hours=1)
            # Formato más amigable de fecha
            label = f"{start.strftime('%d/%m')} de {start.strftime('%H:%M')} a {end.strftime('%H:%M')}"
            new_slots.append({"label": label, "start": start.strftime('%Y-%m-%d %H:%M:%S')})

        options_text = "\n".join([f"{idx+1}. {s['label']}" for idx, s in enumerate(new_slots)])
        
        text = (
            f"Gracias por la información. Hemos encontrado estos horarios disponibles para **{specialty}** 🕒:\n\n"
            f"{options_text}\n\n"
            "¿Cuál prefieres? (Responde con el número 1, 2 o 3)."
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "choose_slot",
            "appointment_data": data,
            "appointment_slots": new_slots,
            "ai_response": text,
        }

    # 5.3 Elegir horario
    if step == "choose_slot":
        idx = None
        if msg in ("1", "2", "3"):
            idx = int(msg) - 1
        if idx is None or idx < 0 or idx >= len(slots):
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "choose_slot",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": "Por favor, elige una de las opciones disponibles escribiendo el número (1, 2 o 3) 🙏.",
            }
        chosen = slots[idx]
        data["appointment_time"] = chosen["start"]
        data["slot_label"] = chosen["label"]
        
        patient = state.get("patient_data") or {}
        name = patient.get("full_name") or "Paciente"
        extra_info = " (Sugerida por IA)" if data.get("choose_by_symptoms") else ""

        resumen = (
            "📝 **Confirmemos los datos de tu cita:**\n\n"
            f"👤 Paciente: {name}\n"
            f"🩺 Especialidad: {data.get('specialty')}{extra_info}\n"
            f"📅 Horario: {data.get('slot_label')}\n"
            f"🗣️ Motivo: {data.get('reason')}\n\n"
            "¿Todo está correcto? Responde **SÍ** para confirmar o **NO** para cancelar."
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "confirm",
            "appointment_data": data,
            "appointment_slots": slots,
            "ai_response": resumen,
        }

    # 5.4 Confirmar y registrar
    if step == "confirm":
        if msg.startswith("s"): # si / sí / sip
            patient = state.get("patient_data") or {}
            payload = {
                "patient": patient,
                "conversation_summary": data.get("reason", ""),
                "symptoms": [data.get("reason", "")],
                "specialty": data.get("specialty", "Medicina General"),
                "risk_level": data.get("risk_level", "BAJO"),
                "possible_diagnosis": data.get("possible_diagnosis", "Evaluación pendiente"),
                "recommended_treatment": data.get("recommended_treatment", "Reposo"),
                "diagnosis_justification": data.get("justification", "Pendiente"),
                "appointment_time": data.get("appointment_time"),
            }
            try:
                res = business_client.create_medical_case(payload)
                if res:
                    case_id = res.get("case", {}).get("id")
                    text = (
                        "✅ **¡Listo! Tu cita ha sido registrada con éxito.**\n\n"
                        f"🆔 Tu número de caso es: **{case_id}**\n"
                        "Te esperamos puntualmente. ¡Que te mejores pronto! 💙\n\n"
                        "___________________________\n"
                        "Si necesitas algo más, escribe:\n"
                        "1️⃣ Agendar otra cita\n"
                        "2️⃣ Consejos de salud\n"
                        "3️⃣ Información médica"
                    )
                    return {
                        **state,
                        "flow": "menu",
                        "appointment_step": None,
                        "appointment_data": None,
                        "appointment_slots": [],
                        "case_id": case_id,
                        "ai_response": text,
                    }
                text = "😓 Ups, tuvimos un pequeño problema al conectar con el sistema. Por favor intenta de nuevo en unos minutos."
                return {**state, "flow": "menu", "appointment_step": None, "ai_response": text}

            except Exception as e:
                print(f"Error: {e}")
                return {**state, "flow": "menu", "appointment_step": None, "ai_response": "😓 Ups, tuvimos un error interno. Intenta más tarde."}

        # No confirmar
        text = (
            "Entendido, he cancelado el registro de la cita 👌.\n\n"
            "¿En qué más puedo ayudarte hoy?\n"
            "1. Agendar una cita\n"
            "2. Tips nutricionales\n"
            "3. Información médica"
        )
        return {
            **state,
            "flow": "menu",
            "appointment_step": None,
            "appointment_data": None,
            "appointment_slots": [],
            "ai_response": text,
        }

    return {**state, "flow": "menu", "appointment_step": None, "ai_response": "Hubo un error en el proceso, por favor escribe '1' para empezar de nuevo."}