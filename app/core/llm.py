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