# app/core/business.py
import requests
from app.config import settings

class BusinessClient:
    def __init__(self):
        # Asegúrate que en .env la URL NO termine en /api, solo el dominio.
        # Ej: https://medisensebackendbs.onrender.com
        self.base_url = settings.BUSINESS_URL

    def _post(self, endpoint, data):
        try:
            print(f"🚀 Enviando a {endpoint}: {data}") 
            # self.base_url + endpoint resultará en: https://.../api/casos...
            return requests.post(f"{self.base_url}{endpoint}", json=data, timeout=10)
        except Exception as e:
            print(f"Error POST {endpoint}: {e}")
            return None

    def get_patient_by_dni(self, dni: str):
        try:
            # CORREGIDO: Agregado /api
            res = requests.get(f"{self.base_url}/api/patients/by-dni/{dni}", timeout=5)
            return res.json() if res.status_code == 200 else None
        except: return None

    def send_verification_code(self, dni: str):
        # CORREGIDO: Agregado /api
        self._post("/api/patients/send-code", {"dni": dni})

    def verify_code(self, dni: str, code: str):
        # CORREGIDO: Agregado /api
        res = self._post("/api/patients/verify-code", {"dni": dni, "code": code})
        if res and res.status_code == 200:
            return res.json().get("patient")
        return None

    def log_wellness(self, patient_data, msg, ai_resp):
        # Lógica de traducción DNI (Correcta, mantenla)
        if patient_data and "document_number" in patient_data:
            patient_data["dni"] = patient_data["document_number"]
            
        payload = {
            "patient": patient_data, 
            "user_message": msg, 
            "ai_response": ai_resp, 
            "category": "wellness"
        }
        # CORREGIDO: Agregado /api
        self._post("/api/wellness/log", payload)

    def log_conversation(self, dni, sender, message, case_id=None):
        # CORREGIDO: Agregado /api
        self._post("/api/conversations/log", {
            "dni": dni, "sender": sender, "message": message, "case_id": case_id
        })

    def create_medical_case(self, data):
        patient = data.get("patient", {})
        
        # Lógica de traducción DNI (Correcta, mantenla)
        if "document_number" in patient:
            patient["dni"] = patient["document_number"]
            data["patient"] = patient
        
        # CORREGIDO: Agregado /api
        res = self._post("/api/cases/from-ia", data)
        return res.json() if res and res.status_code == 200 else None

business_client = BusinessClient()