from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes import (
    verification_node,
    menu_node,
    wellness_node,
    medical_node,
    appointment_node,
)


# ==========================================================
# RUTAS DEL GRAFO
# ==========================================================


def route_verification(state: AgentState):
    """
    Decidimos a qué nodo ir después de ejecutar 'verification':

    - Si NO está verificado → seguimos en 'verification' (pero el turno termina).
    - Si se acaba de verificar (just_verified = True) → terminamos el turno
      (ya enviamos el menú desde verification_node).
    - Si ya estaba verificado:
        * Si tiene un flujo activo (appointment / wellness / medical) → ir directo ahí.
        * Si no tiene flujo → ir al menú principal.
    """
    if not state.get("is_verified"):
        # Todavía no pasó verificación (seguimos en el flujo de verificación)
        return "verification"

    # Turno en el que se validó el código: verification_node ya envió el menú
    if state.get("just_verified"):
        return "verification"  # mapeado a END más abajo

    # Usuario ya verificado de antes: retomamos el flujo actual
    flow = state.get("flow")
    if flow in ("appointment", "wellness", "medical"):
        return flow

    # Sin flujo activo → ir al menú
    return "menu"


def route_menu(state: AgentState):
    """
    Decide a qué nodo ir DESPUÉS de ejecutar 'menu_node'.

    ⚠ IMPORTANTE:
    - Para 'wellness' e 'medical' SÍ saltamos en el mismo turno.
    - Para 'appointment' NO avanzamos en este turno: solo dejamos
      flow="appointment" y terminamos. El siguiente mensaje ya entra
      directo a appointment_node.
    """
    flow = state.get("flow")

    # Saltos inmediatos (mismo turno)
    if flow == "wellness":
        return "wellness"
    if flow == "medical":
        return "medical"

    # Para 'appointment' o cualquier otra cosa, terminamos turno.
    return END


# ==========================================================
# DEFINICIÓN DEL WORKFLOW
# ==========================================================

workflow = StateGraph(AgentState)

# Nodos
workflow.add_node("verification", verification_node)
workflow.add_node("menu", menu_node)
workflow.add_node("wellness", wellness_node)
workflow.add_node("medical", medical_node)
workflow.add_node("appointment", appointment_node)

# Punto de entrada
workflow.set_entry_point("verification")

# Después de 'verification' decidimos si:
# - seguimos verificando
# - terminamos (just_verified)
# - vamos al menú
# - retomamos un flujo ya activo (appointment / wellness / medical)
workflow.add_conditional_edges(
    "verification",
    route_verification,
    {
        # Cualquier retorno "verification" termina el turno
        # (sea porque aún falta código/DNI o porque just_verified=True)
        "verification": END,
        "menu": "menu",
        "appointment": "appointment",
        "wellness": "wellness",
        "medical": "medical",
    },
)

# Desde el menú:
# - wellness / medical → se ejecutan en el mismo turno
# - appointment → se deja marcado el flujo pero NO se ejecuta aquí
workflow.add_conditional_edges(
    "menu",
    route_menu,
    {
        "wellness": "wellness",
        "medical": "medical",
        END: END,
    },
)

# Nodos terminales para este turno
workflow.add_edge("wellness", END)
workflow.add_edge("medical", END)
workflow.add_edge("appointment", END)

# Grafo compilado
app_graph = workflow.compile()


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

# Especialidades disponibles explícitamente en el centro médico
# (los valores deben coincidir con la columna specialty de la tabla users)
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

# Mapa general para normalizar texto libre a especialidades de BD
SPECIALTY_MAP = {
    # Medicina general
    "general": "Medicina General",
    "medicina general": "Medicina General",
    "medicina": "Medicina General",
    "consulta general": "Medicina General",
    "clinica general": "Medicina General",

    # Nutrición
    "nutricion": "Nutricion",
    "nutrición": "Nutricion",
    "nutricionista": "Nutricion",

    # Dermatología
    "dermatologia": "Dermatologia",
    "dermatología": "Dermatologia",
    "piel": "Dermatologia",

    # Oftalmología
    "oftalmologia": "Oftalmologia",
    "oftalmología": "Oftalmologia",
    "ojos": "Oftalmologia",

    # Ginecología
    "ginecologia": "Ginecologia",
    "ginecología": "Ginecologia",

    # Cirugía plástica
    "cirugia plastica": "Cirugia Plastica",
    "cirugía plástica": "Cirugia Plastica",

    # Traumatología
    "traumatologia": "Traumatologia",
    "traumatología": "Traumatologia",

    # Neumología
    "neumologia": "Neumologia",
    "neumología": "Neumologia",

    # Cardiología
    "cardiologia": "Cardiologia",
    "cardiología": "Cardiologia",
    "corazon": "Cardiologia",
    "corazón": "Cardiologia",

    # Psicología
    "psicologia": "Psicologia",
    "psicología": "Psicologia",

    # Odontología
    "odontologia": "Odontologia",
    "odontología": "Odontologia",
    "dentista": "Odontologia",

    # Fisioterapia
    "fisioterapia": "Fisioterapia",
    "terapia fisica": "Fisioterapia",
    "terapia física": "Fisioterapia",

    # Obstetricia
    "obstetricia": "Obstetricia",
    "obstetra": "Obstetricia",
}


def normalize_specialty(raw: str | None) -> str:
    """
    Normaliza la especialidad sugerida por el LLM a alguno de los valores
    válidos para la BD. Por defecto devuelve Medicina General.
    """
    if not raw:
        return "Medicina General"

    key = raw.strip().lower()

    # Coincidencia exacta
    if key in SPECIALTY_MAP:
        return SPECIALTY_MAP[key]

    # Coincidencia por inclusión (ej. "cardiología pediátrica")
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
            # Cuando se verifica, limpiamos cualquier flujo viejo
            return {
                **state,
                "is_verified": True,
                "patient_data": patient,
                "verification_step": "verified",
                "just_verified": True,   # Turno en el que mostramos menú
                "flow": "menu",
                "appointment_step": None,
                "appointment_data": {},
                "appointment_slots": [],
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
            "13. Obstetricia\n"
            "14. Que la IA elija la especialidad según mis síntomas"
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

        # Opción 14: dejar que la IA elija según síntomas
        if msg == "14" or "elige" in msg or "sintoma" in msg or "síntoma" in msg:
            data["choose_by_symptoms"] = True
            # todavía NO fijamos especialidad, la pondremos en ask_reason
            text = (
                "Perfecto. Cuéntame en una frase qué síntomas tienes y desde cuándo, "
                "y yo elegiré la especialidad más adecuada para tu cita.\n\n"
                "Por ejemplo: 'tengo dolor de cabeza desde hace 3 días con fiebre ligera'."
            )
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "ask_reason",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": text,
            }

        # Opción 1–13 numérica
        if msg in APPOINTMENT_SPECIALTIES:
            specialty = APPOINTMENT_SPECIALTIES[msg]
        else:
            # Texto libre (ej: "quiero nutrición", "cita con cardiología", etc.)
            for val in APPOINTMENT_SPECIALTIES.values():
                # Solo comparamos con la primera palabra (Medicina, Nutricion, etc.)
                if val.split()[0].lower() in msg:
                    specialty = val
                    break

        if not specialty:
            text = (
                "No entendí la especialidad.\n"
                "Elige una opción respondiendo solo con el número:\n"
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
                "13. Obstetricia\n"
                "14. Que la IA elija la especialidad según mis síntomas"
            )
            return {
                **state,
                "flow": "appointment",
                "appointment_step": "ask_specialty",
                "appointment_data": data,
                "appointment_slots": slots,
                "ai_response": text,
            }

        # Especialidad elegida explícitamente
        data["specialty"] = specialty
        data["choose_by_symptoms"] = False

        text = (
            f"Perfecto, agendaremos una cita en *{specialty}*.\n\n"
            "Cuéntame en una frase el motivo de tu consulta, incluyendo desde cuándo tienes "
            "los síntomas (por ejemplo: dolor de cabeza desde hace 3 días con fiebre ligera)."
        )
        return {
            **state,
            "flow": "appointment",
            "appointment_step": "ask_reason",
            "appointment_data": data,
            "appointment_slots": slots,
            "ai_response": text,
        }

    # 5.2 Capturar motivo (y si aplica, dejar que la IA elija la especialidad)
    if step == "ask_reason":
        data["reason"] = msg_raw

        # Llamamos al LLM para extraer info clínica y especialidad sugerida
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
        except Exception as e:
            print(f"Error en DIAGNOSIS_EXTRACTION dentro de appointment_node: {e}")
            data.setdefault("risk_level", "BAJO")
            data.setdefault("possible_diagnosis", "Evaluación pendiente")
            data.setdefault("recommended_treatment", "Reposo")
            data.setdefault("justification", "")

        # Si por alguna razón todavía no hay especialidad, usamos Medicina General
        specialty = data.get("specialty") or "Medicina General"
        data["specialty"] = specialty

        # Generar 3 horarios de 1 hora a partir de mañana
        base_day = datetime.now() + timedelta(days=1)
        base_day = base_day.replace(minute=0, second=0, microsecond=0)

        new_slots = []
        for hour in [9, 10, 11]:  # 09:00-10:00, 10:00-11:00, 11:00-12:00
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
            f"en *{specialty}* (todas las citas son de 1 hora):\n\n"
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

        extra_especialidad = (
            " (sugerida por la IA según tus síntomas)"
            if data.get("choose_by_symptoms")
            else ""
        )

        resumen = (
            "Este es el resumen de tu cita:\n"
            f"- Paciente: {name}\n"
            f"- DNI: {patient.get('document_number', '')}\n"
            f"- Especialidad: {data.get('specialty')}{extra_especialidad}\n"
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
# app/agents/prompts.py
TRIAGE_PROMPT = """
Clasifica el siguiente mensaje de un usuario de WhatsApp.
Responde SOLAMENTE una de estas palabras:
- MEDICAL: Si menciona síntomas, dolor, enfermedad, o pide cita.
- WELLNESS: Si pide consejos de nutrición, ejercicio o sueño.
- OTHER: Saludos, agradecimientos o temas irrelevantes.

Mensaje: "{message}"
"""

MEDICAL_RAG_PROMPT = """
Eres un asistente médico clínico inteligente de MediSense. Tu objetivo es orientar y facilitar la atención.

CONTEXTO CLÍNICO (Guías):
{context}

HISTORIAL:
{history}

ESTADO DE GESTIÓN (Información del Sistema):
{system_status}

INSTRUCCIONES:
1. Si el usuario describe síntomas, usa el CONTEXTO para orientar (cita la fuente si es posible).
2. Si el "ESTADO DE GESTIÓN" indica que se ha generado un pre-ingreso o cita, CONFIRMA al usuario que su solicitud fue registrada exitosamente.
3. Si el usuario pide una cita y NO hay info en "ESTADO DE GESTIÓN", dile que procederás a capturar sus datos o invítalo a describir sus síntomas para registrarlo.
4. Sé empático. No inventes tratamientos farmacológicos.

Pregunta del paciente: {question}
"""

DIAGNOSIS_EXTRACTION_PROMPT = """
Analiza este relato de síntomas: "{text}"
Extrae la información en JSON puro (sin markdown):
{{
    "risk_level": "BAJO/MEDIO/ALTO",
    "possible_diagnosis": "Hipótesis diagnóstica breve",
    "justification": "Breve explicación basada en síntomas",
    "recommended_treatment": "Medidas generales (reposo, hidratación, etc)",
    "specialty": "Especialidad sugerida (General, Nutrición, Cardiología, etc)"
}}
"""

WELLNESS_PROMPT = """
Eres un coach de bienestar. Da un consejo motivador y breve (max 3 líneas) sobre: {message}.
"""

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

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from twilio.rest import Client
from app.config import settings
from app.agents.graph import app_graph
from app.core.business import business_client

# Router principal (usado en /api/webhook)
router = APIRouter()

client = Client(settings.TWILIO_SID, settings.TWILIO_TOKEN)

memory_store = {}  # En prod usar Redis


async def process_message(user_phone: str, body: str, sender: str):
    """Procesa el mensaje en background para no bloquear a Twilio"""
    
    # Recuperar estado
    state = memory_store.get(user_phone, {
        "whatsapp_number": user_phone, "user_message": "",
        "is_verified": False, "verification_step": "ask_dni",
        "history": [], "patient_data": None
    })
    state["user_message"] = body

    # Log usuario
    if state.get("dni"):
        business_client.log_conversation(state["dni"], "user", body)

    # Ejecutar Agente
    try:
        result = app_graph.invoke(state)
        ai_response = result.get("ai_response", "Error interno.")
        
        # Actualizar memoria
        result["history"] = result.get("history", []) + [
            f"User: {body}", f"AI: {ai_response}"
        ]
        memory_store[user_phone] = result
        
        # Log AI
        if state.get("dni"):
            business_client.log_conversation(
                state["dni"], "ai", ai_response, result.get("case_id")
            )
            
        # Enviar Respuesta a WhatsApp
        client.messages.create(
            from_=settings.TWILIO_FROM,
            body=ai_response,
            to=sender
        )

    except Exception as e:
        print(f"Error processing: {e}")


# --------------------------
# Ruta oficial (API REST)
# --------------------------
@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    sender = form.get("From")
    body = form.get("Body", "")
    
    if not sender or not body:
        return PlainTextResponse("No content")

    user_phone = sender.replace("whatsapp:", "")
    
    # Procesar en Background (Respuesta inmediata a Twilio)
    background_tasks.add_task(process_message, user_phone, body, sender)
    
    return PlainTextResponse("OK")


# -----------------------------------
# Ruta duplicada (para Twilio /webhook)
# -----------------------------------
legacy_router = APIRouter()

@legacy_router.post("/webhook")
async def legacy_webhook(request: Request, background_tasks: BackgroundTasks):
    """Versión sin prefix /api, para Twilio"""
    return await whatsapp_webhook(request, background_tasks)

import requests
from app.config import settings


class BusinessClient:
    def __init__(self):
        # La variable de entorno YA incluye /api al final
        # Ej: https://medisensebackendbs.onrender.com/api
        self.base_url = settings.BUSINESS_URL

    def _post(self, endpoint: str, data: dict):
        """
        Helper para POST con logs de debugging.
        """
        try:
            full_url = f"{self.base_url}{endpoint}"
            print(f"🚀 POST → {full_url} | payload={data}")
            res = requests.post(full_url, json=data, timeout=10)
            print(f"🔙 Respuesta {full_url}: {res.status_code} {res.text}")
            return res
        except Exception as e:
            print(f"❌ Error POST {endpoint}: {e}")
            return None

    def get_patient_by_dni(self, dni: str):
        try:
            url = f"{self.base_url}/patients/by-dni/{dni}"
            print(f"🔎 GET → {url}")
            res = requests.get(url, timeout=5)
            print(f"🔙 Respuesta GET {url}: {res.status_code} {res.text}")
            return res.json() if res.status_code == 200 else None
        except Exception as e:
            print(f"❌ Error GET /patients/by-dni: {e}")
            return None

    def send_verification_code(self, dni: str):
        self._post("/patients/send-code", {"dni": dni})

    def verify_code(self, dni: str, code: str):
        res = self._post("/patients/verify-code", {"dni": dni, "code": code})
        if res and res.status_code == 200:
            try:
                return res.json().get("patient")
            except Exception as e:
                print(f"❌ Error leyendo JSON verify-code: {e}")
                return None
        return None

    def log_wellness(self, patient_data, msg: str, ai_resp: str):
        if patient_data and "document_number" in patient_data:
            patient_data["dni"] = patient_data["document_number"]
            
        payload = {
            "patient": patient_data, 
            "user_message": msg, 
            "ai_response": ai_resp, 
            "category": "wellness",
        }
        self._post("/wellness/log", payload)

    def log_conversation(self, dni: str, sender: str, message: str, case_id=None):
        payload = {
            "dni": dni,
            "sender": sender,
            "message": message,
            "case_id": case_id,
        }
        self._post("/conversations/log", payload)

    def create_medical_case(self, data: dict):
        """
        Llama a /api/cases/from-ia y devuelve el JSON si status 200.
        Añade logs detallados para entender por qué falla.
        """
        patient = data.get("patient", {})
        
        # Traducir document_number → dni para backend de negocio
        if "document_number" in patient:
            patient["dni"] = patient["document_number"]
            data["patient"] = patient
        
        res = self._post("/cases/from-ia", data)
        if not res:
            print("❌ No hubo respuesta del backend de negocio al crear caso.")
            return None

        print(f"📦 Resultado create_medical_case: {res.status_code} {res.text}")
        if res.status_code == 200:
            try:
                return res.json()
            except Exception as e:
                print(f"❌ Error parseando JSON create_medical_case: {e}")
                return None

        # Aquí ya sabemos que hubo error de negocio (400, 500, etc.)
        return None


business_client = BusinessClient()


# app/core/knowledge.py
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from app.config import settings
from app.core.llm import embeddings_model

class KnowledgeBase:
    def __init__(self):
        if settings.SEARCH_ENDPOINT and settings.SEARCH_KEY:
            self.client = SearchClient(
                endpoint=settings.SEARCH_ENDPOINT,
                index_name=settings.SEARCH_INDEX,
                credential=AzureKeyCredential(settings.SEARCH_KEY)
            )
        else:
            self.client = None
            print("⚠️ Azure Search no configurado.")

    def search(self, query: str, top: int = 3) -> str:
        """
        Busca en los documentos que tu Azure Function ya indexó.
        """
        if not self.client:
            return ""

        try:
            # 1. Vectorizar la pregunta del usuario
            query_vector = embeddings_model.embed_query(query)
            
            # 2. Configurar búsqueda vectorial
            # IMPORTANTE: Revisa en tu índice cómo se llama el campo vectorial.
            # Por defecto suele ser 'contentVector', 'vector' o 'embedding'.
            # Aquí asumo 'contentVector'. Ajusta si es necesario.
            vector_query = VectorizedQuery(
                vector=query_vector, 
                k_nearest_neighbors=top, 
                fields="content_vector" 
            )

            # 3. Ejecutar búsqueda Híbrida (Texto + Vector)
            results = self.client.search(
                search_text=query,
                vector_queries=[vector_query],
                top=top,
                select=["content", "source", "title"] # Ajusta a los campos que tenga tu índice
            )
            
            # 4. Formatear
            context_parts = []
            for r in results:
                # Fallbacks por si tu indice tiene nombres de campos distintos
                source = r.get("source") or r.get("title") or "Documento Médico"
                content = r.get("content") or ""
                context_parts.append(f"--- Fuente: {source} ---\n{content}\n")
            
            return "\n".join(context_parts) if context_parts else "No se encontró información específica en los protocolos."

        except Exception as e:
            print(f"❌ Error buscando en Azure Search: {e}")
            return ""

knowledge_base = KnowledgeBase()

# app/core/llm.py
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from app.config import settings

# 1. Modelo de Chat (GPT-4o)
llm = AzureChatOpenAI(
    azure_deployment=settings.AZURE_DEPLOYMENT,
    openai_api_version=settings.AZURE_API_VERSION,
    azure_endpoint=settings.AZURE_ENDPOINT,
    api_key=settings.AZURE_API_KEY,
    temperature=0.3 # Bajo para precisión médica
)

# 2. Modelo de Embeddings (Ada-002)
# Usado para vectorizar la pregunta del usuario antes de buscar en Azure Search
embeddings_model = AzureOpenAIEmbeddings(
    azure_deployment=settings.AZURE_EMBEDDING_DEPLOYMENT,
    openai_api_version=settings.AZURE_API_VERSION,
    azure_endpoint=settings.AZURE_ENDPOINT,
    api_key=settings.AZURE_API_KEY,
)


# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Server & Business
    BUSINESS_URL = os.getenv("BUSINESS_BACKEND_URL")
    
    # Azure Chat
    AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
    AZURE_DEPLOYMENT = os.getenv("AZURE_DEPLOYMENT_NAME")
    
    # Azure Embeddings (Para Query)
    AZURE_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT")
    
    # Azure Search
    SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_SERVICE_ENDPOINT")
    SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX_NAME")
    SEARCH_KEY = os.getenv("AZURE_SEARCH_API_KEY")
    
    # Twilio
    TWILIO_SID = os.getenv("TWILIO_SID")
    TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
    TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")

settings = Settings()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.webhook import router, legacy_router

app = FastAPI(title="MediSense AI Backend")

# CORS Config
origins = ["*"]  # Ajustar en producción

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas oficiales de la API
app.include_router(router, prefix="/api")

# Ruta espejo para Twilio (sin /api)
app.include_router(legacy_router)

@app.get("/")
def home():
    return {"status": "AI Backend Online (RAG Mode)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

