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