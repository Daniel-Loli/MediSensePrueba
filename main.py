from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_WHATSAPP = os.getenv("TWILIO_WHATSAPP_NUMBER")

client = Client(TWILIO_SID, TWILIO_TOKEN)

@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()
    sender = form.get("From")
    body = form.get("Body")

    reply = f"Hola! Recibí tu mensaje: '{body}'"
    client.messages.create(
        from_=TWILIO_WHATSAPP,
        body=reply,
        to=sender
    )
    return PlainTextResponse("OK")
