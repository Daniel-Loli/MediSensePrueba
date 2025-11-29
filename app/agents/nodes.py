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
# CONSTANTES / HELPERS
# ==========================================================

MENU_TEXT = (
    "Identidad verificada ✅.\n\n"
    "Por favor elige una opción respondiendo solo con el número:\n"
    "1. Registrar una cita\n"
    "2. Tips nutricionales\n"
    "3. Información sobre un tema médico específico"
)

# Mapa de especialidades que usará el flujo de cita
APPOINTMENT_SPECIALTIES = {
    "1": "Medicina General",
    "2": "Obstetricia",
    "3": "Nutricion",
}

# Mapa general para normalizar texto libre a especialidades de BD
SPECIALTY_MAP = {
    # Medicina general
    "general": "Medicina General",
    "medicina general": "Medicina General",
    "medicina": "Medicina General",
    "consulta general": "Medicina General",

    # Nutrición
    "nutricion": "Nutricion",
    "nutrición": "Nutricion",

    # Obstetricia
    "obstetricia": "Obstetricia",

    # (si luego agregas más especialidades, las mapeas aquí)
}


def normalize_specialty(raw: str | None) -> str:
    if not raw:
        return "Medicina General"
    key = raw.strip().lower()
    return SPECIALTY_MAP.get(key, "Medicina General")


# ==========================================================
# NODO 1: VERIFICACIÓN (DNI + CÓDIGO)
# ==========================================================

def verification_node(state: AgentState) -> AgentState:
    msg = state["user_message"].strip()
    step = state.get("verification_step", "ask_dni")

    # Siempre, por defecto, no estamos "recién verificados"
    state = {**state, "just_verified": False}

    # 1) Pedir DNI
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
                        f"Hola {exists['patient']['full_name']}.\n"
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

    # 2) Validar código
    elif step == "ask_code":
        patient = business_client.verify_code(state["dni"], msg)
        if patient:
            # En este mismo turno enviamos el menú
            return {
                **state,
                "is_verified": True,
                "patient_data": patient,
                "verification_step": "verified",
                "just_verified": True,   # <-- clave para que el grafo termine aquí
                "flow": "menu",
                "ai_response": MENU_TEXT,
            }
        return {**state, "ai_response": "Código incorrecto. Inténtalo nuevamente."}

    # 3) Ya verificado en turnos posteriores → no hacemos nada aquí
    elif step == "verified":
        return {**state, "just_verified": False}

    return state


# ==========================================================
# NODO 2: MENÚ PRINCIPAL (1 / 2 / 3)
# ==========================================================

def menu_node(state: AgentState) -> AgentState:
    msg_raw = state["user_message"].strip()
    msg = msg_raw.lower()

    option = None

    # Aceptar número o texto
    if msg in ("1", "2", "3"):
        option = msg
    elif "cita" in msg or "agendar" in msg or "registrar" in msg:
        option = "1"
    elif "nutric" in msg:
        option = "2"
    elif "informacion" in msg or "información" in msg or "tema" in msg:
        option = "3"

    # --- Opción 1: Registrar cita ---
    if option == "1":
        text = (
            "Perfecto, vamos a registrar tu cita.\n\n"
            "Primero, elige la especialidad respondiendo con el número:\n"
            "1. Medicina General\n"
            "2. Obstetricia\n"
            "3. Nutrición"
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "ask_specialty",
            "appointment_data": {},
            "appointment_slots": [],
            "ai_response": text,
        }

    # --- Opción 2: Tips nutricionales (wellness) ---
    if option == "2":
        text = (
            "Genial, te puedo ayudar con tips nutricionales.\n"
            "Cuéntame brevemente qué te gustaría mejorar "
            "(por ejemplo: bajar de peso, ganar masa muscular, controlar colesterol, etc.)."
        )
        return {
            **state,
            "flow": "wellness",
            "ai_response": text,
        }

    # --- Opción 3: Información médica específica ---
    if option == "3":
        text = (
            "De acuerdo, dime sobre qué tema médico específico quieres información "
            "(por ejemplo: hipertensión, diabetes, migrañas, etc.)."
        )
        return {
            **state,
            "flow": "medical",
            "ai_response": text,
        }

    # --- Opción no válida → repetir menú ---
    return {
        **state,
        "flow": "menu",
        "ai_response": (
            "No entendí tu respuesta.\n\n" + MENU_TEXT
        ),
    }


# ==========================================================
# NODO 3: WELLNESS (TIPS NUTRICIONALES)
# ==========================================================

def wellness_node(state: AgentState) -> AgentState:
    resp = llm.invoke([
        HumanMessage(content=WELLNESS_PROMPT.format(message=state["user_message"]))
    ])
    business_client.log_wellness(
        state.get("patient_data"),
        state["user_message"],
        resp.content,
    )
    return {**state, "ai_response": resp.content}


# ==========================================================
# NODO 4: INFORMACIÓN MÉDICA (SIN REGISTRAR CITA)
# ==========================================================

def medical_node(state: AgentState) -> AgentState:
    user_msg = state["user_message"]

    # 1. RAG: Buscar contexto clínico
    context = knowledge_base.search(user_msg)
    history_str = "\n".join(state.get("history", [])[-4:])

    # 2. Generar respuesta informativa (sin crear casos)
    prompt = MEDICAL_RAG_PROMPT.format(
        context=context,
        history=history_str,
        system_status="No se ha realizado ninguna acción administrativa.",
        question=user_msg,
    )

    resp = llm.invoke([HumanMessage(content=prompt)])
    ai_text = resp.content

    return {**state, "ai_response": ai_text}


# ==========================================================
# NODO 5: FLUJO DE CITA (PASO A PASO)
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

        # Número 1/2/3
        if msg in APPOINTMENT_SPECIALTIES:
            specialty = APPOINTMENT_SPECIALTIES[msg]
        else:
            # Texto libre (ej: "quiero ginecología")
            for val in APPOINTMENT_SPECIALTIES.values():
                if val.split()[0].lower() in msg:  # general / obstetricia / nutricion
                    specialty = val
                    break

        if not specialty:
            text = (
                "No entendí la especialidad.\n"
                "Elige una opción respondiendo solo con el número:\n"
                "1. Medicina General\n"
                "2. Obstetricia\n"
                "3. Nutrición"
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
        text = (
            f"Perfecto, agendaremos una cita en *{specialty}*.\n\n"
            "Cuéntame en una frase el motivo de tu consulta "
            "tienes los síntomas (por ejemplo: dolor de cabeza desde hace 3 días con fiebre ligera)."
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

        # Generar 3 horarios de 1 hora a partir de mañana
        base_day = datetime.now() + timedelta(days=1)
        base_day = base_day.replace(minute=0, second=0, microsecond=0)

        new_slots = []
        for i, hour in enumerate([9, 10, 11]):  # 09:00-10:00, 10:00-11:00, 11:00-12:00
            start = base_day.replace(hour=hour)
            end = start + timedelta(hours=1)
            label = f"{start.strftime('%d/%m/%Y')} de {start.strftime('%H:%M')} a {end.strftime('%H:%M')}"
            new_slots.append({
                "label": label,
                "start": start.strftime('%Y-%m-%d %H:%M:%S'),
            })

        options_text = "\n".join(
            [f"{idx+1}. {s['label']}" for idx, s in enumerate(new_slots)]
        )

        text = (
            "Gracias. Ahora elige un horario disponible para tu cita "
            "(todas las citas son de 1 hora):\n\n"
            f"{options_text}\n\n"
            "Responde con el número de la opción."
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
            text = "Por favor responde con el número de una de las opciones indicadas (1, 2 o 3)."
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "choose_slot",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": text,
            }

        chosen = slots[idx]
        data["appointment_time"] = chosen["start"]
        data["slot_label"] = chosen["label"]

        patient = state.get("patient_data") or {}
        name = patient.get("full_name") or f"DNI {patient.get('document_number', '')}"

        resumen = (
            "Este es el resumen de tu cita:\n"
            f"- Paciente: {name}\n"
            f"- DNI: {patient.get('document_number', '')}\n"
            f"- Especialidad: {data.get('specialty')}\n"
            f"- Motivo: {data.get('reason')}\n"
            f"- Fecha y hora: {data.get('slot_label')}\n\n"
            "¿Deseas *confirmar* el registro de esta cita?\n"
            "Responde *SI* o *NO*."
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
        if msg.startswith("s"):  # sí / si
            patient = state.get("patient_data") or {}
            payload = {
                "patient": patient,
                "conversation_summary": data.get("reason", ""),
                "symptoms": [data.get("reason", "")],
                "specialty": data.get("specialty", "Medicina General"),
                "risk_level": "BAJO",
                "possible_diagnosis": "Evaluación pendiente",
                "recommended_treatment": "Reposo",
                "diagnosis_justification": "Pendiente",
                "appointment_time": data.get("appointment_time"),
            }

            try:
                res = business_client.create_medical_case(payload)
                if res:
                    case_id = res.get("case", {}).get("id")
                    text = (
                        "✅ Tu cita ha sido registrada exitosamente.\n\n"
                        f"ID de caso: {case_id}\n"
                        f"Fecha y hora: {data.get('slot_label')}\n"
                        f"Especialidad: {data.get('specialty')}\n\n"
                        "Si deseas otra cosa, puedes escribir:\n"
                        "1 para registrar otra cita\n"
                        "2 para tips nutricionales\n"
                        "3 para información médica."
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

                text = (
                    "⚠️ Ocurrió un error al registrar tu cita en el sistema.\n"
                    "Por favor intenta más tarde o comunícate con el centro médico."
                )
                return {
                    **state,
                    "flow": "menu",
                    "appointment_step": None,
                    "appointment_data": None,
                    "appointment_slots": [],
                    "ai_response": text,
                }

            except Exception as e:
                print(f"Error creando cita desde appointment_node: {e}")
                text = (
                    "⚠️ Ocurrió un error interno al registrar tu cita.\n"
                    "Por favor intenta más tarde o comunícate con el centro médico."
                )
                return {
                    **state,
                    "flow": "menu",
                    "appointment_step": None,
                    "appointment_data": None,
                    "appointment_slots": [],
                    "ai_response": text,
                }

        # Usuario NO confirma
        text = (
            "Perfecto, no se registró ninguna cita.\n\n"
            "Si deseas, puedes volver a empezar escribiendo:\n"
            "1 para registrar una cita\n"
            "2 para tips nutricionales\n"
            "3 para información médica."
        )
        return {
            **state,
            "flow": "menu",
            "appointment_step": None,
            "appointment_data": None,
            "appointment_slots": [],
            "ai_response": text,
        }

    # Fallback
    return {
        **state,
        "flow": "menu",
        "appointment_step": None,
        "ai_response": "He tenido un problema con el flujo de la cita. Por favor escribe 1 para intentar nuevamente.",
    }


# ==========================================================
# (Opcional) Triaging general (por si luego lo quieres reutilizar)
# ==========================================================

def triage_node(state: AgentState) -> AgentState:
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
