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
