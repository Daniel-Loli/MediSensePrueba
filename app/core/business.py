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
