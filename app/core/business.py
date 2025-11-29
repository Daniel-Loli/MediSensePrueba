import requests
from app.config import settings

class BusinessClient:
    def __init__(self):
        # La variable de entorno YA incluye /api al final
        # Ej: https://medisensebackendbs.onrender.com/api
        self.base_url = settings.BUSINESS_URL

    def _post(self, endpoint, data):
        try:
            # DEBUG: Imprimir URL completa para verificar
            full_url = f"{self.base_url}{endpoint}"
            print(f"🚀 Enviando a {full_url} | Datos: {data}") 
            return requests.post(full_url, json=data, timeout=10)
        except Exception as e:
            print(f"Error POST {endpoint}: {e}")
            return None

    def get_patient_by_dni(self, dni: str):
        try:
            # Sin /api aquí
            res = requests.get(f"{self.base_url}/patients/by-dni/{dni}", timeout=5)
            return res.json() if res.status_code == 200 else None
        except: return None

    def send_verification_code(self, dni: str):
        # Sin /api aquí
        self._post("/patients/send-code", {"dni": dni})

    def verify_code(self, dni: str, code: str):
        # Sin /api aquí
        res = self._post("/patients/verify-code", {"dni": dni, "code": code})
        if res and res.status_code == 200:
            return res.json().get("patient")
        return None

    def log_wellness(self, patient_data, msg, ai_resp):
        # MANTENEMOS LA TRADUCCIÓN DEL DNI
        if patient_data and "document_number" in patient_data:
            patient_data["dni"] = patient_data["document_number"]
            
        payload = {
            "patient": patient_data, 
            "user_message": msg, 
            "ai_response": ai_resp, 
            "category": "wellness"
        }
        # Sin /api aquí
        self._post("/wellness/log", payload)

    def log_conversation(self, dni, sender, message, case_id=None):
        # Sin /api aquí
        self._post("/conversations/log", {
            "dni": dni, "sender": sender, "message": message, "case_id": case_id
        })

    def create_medical_case(self, data):
        patient = data.get("patient", {})
        
        # MANTENEMOS LA TRADUCCIÓN DEL DNI (CRÍTICO)
        if "document_number" in patient:
            patient["dni"] = patient["document_number"]
            data["patient"] = patient
        
        # Sin /api aquí
        res = self._post("/cases/from-ia", data)
        return res.json() if res and res.status_code == 200 else None

business_client = BusinessClient()