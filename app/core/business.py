# app/core/business.py
import requests
from app.config import settings

class BusinessClient:
    def __init__(self):
        self.base_url = settings.BUSINESS_URL

    def _post(self, endpoint, data):
        try:
            # DEBUG: Esto imprimirá en consola qué estamos enviando
            print(f"🚀 Enviando a {endpoint}: {data}") 
            return requests.post(f"{self.base_url}{endpoint}", json=data, timeout=10)
        except Exception as e:
            print(f"Error POST {endpoint}: {e}")
            return None

    def get_patient_by_dni(self, dni: str):
        try:
            res = requests.get(f"{self.base_url}/patients/by-dni/{dni}", timeout=5)
            return res.json() if res.status_code == 200 else None
        except: return None

    def send_verification_code(self, dni: str):
        self._post("/patients/send-code", {"dni": dni})

    def verify_code(self, dni: str, code: str):
        res = self._post("/patients/verify-code", {"dni": dni, "code": code})
        if res and res.status_code == 200:
            return res.json().get("patient")
        return None

    def log_wellness(self, patient_data, msg, ai_resp):
        # 1. TRADUCCIÓN: Aseguramos que exista el campo 'dni' para Node.js
        if patient_data and "document_number" in patient_data:
            patient_data["dni"] = patient_data["document_number"]
            
        payload = {
            "patient": patient_data, 
            "user_message": msg, 
            "ai_response": ai_resp, 
            "category": "wellness"
        }
        self._post("/wellness/log", payload)

    def log_conversation(self, dni, sender, message, case_id=None):
        self._post("/conversations/log", {
            "dni": dni, "sender": sender, "message": message, "case_id": case_id
        })

    def create_medical_case(self, data):
        # 1. RECUPERAR DATOS DEL PACIENTE
        patient = data.get("patient", {})
        
        # 2. TRADUCCIÓN CRÍTICA: 
        # Node.js (server.js) busca 'patient.dni', pero la BD nos dio 'patient.document_number'.
        # Aquí creamos la copia del dato para que Node.js lo encuentre.
        if "document_number" in patient:
            patient["dni"] = patient["document_number"]
            # Actualizamos el objeto dentro de data
            data["patient"] = patient
        
        # 3. ENVIAR A NODE.JS
        res = self._post("/cases/from-ia", data)
        return res.json() if res and res.status_code == 200 else None

business_client = BusinessClient()