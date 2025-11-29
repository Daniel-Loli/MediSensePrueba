import os
import sys
# Hack para importar app.config desde scripts/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import AzureOpenAIEmbeddings
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField, SearchField,
    SearchFieldDataType, VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile
)
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from app.config import settings
import uuid

def run_ingest():
    print("🚀 Iniciando Ingesta de Documentos...")
    
    # 1. Cargar PDFs
    path = "docs"
    if not os.path.exists(path): os.makedirs(path)
    loader = DirectoryLoader(path, glob="*.pdf", loader_cls=PyPDFLoader)
    docs = loader.load()
    if not docs:
        print("❌ No hay PDFs en la carpeta 'docs/'.")
        return

    # 2. Split
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    print(f"📦 Procesando {len(chunks)} fragmentos...")

    # 3. Setup Azure Search
    cred = AzureKeyCredential(settings.SEARCH_KEY)
    index_client = SearchIndexClient(settings.SEARCH_ENDPOINT, cred)
    
    # Definir índice
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="source", type=SearchFieldDataType.String),
        SearchField(name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True, vector_search_dimensions=1536, vector_search_profile_name="my-profile")
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="my-hnsw")],
        profiles=[VectorSearchProfile(name="my-profile", algorithm_configuration_name="my-hnsw")]
    )
    index = SearchIndex(name=settings.SEARCH_INDEX, fields=fields, vector_search=vector_search)
    index_client.create_or_update_index(index)

    # 4. Embed & Upload
    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=settings.AZURE_EMBEDDING_DEPLOYMENT,
        openai_api_version=settings.AZURE_API_VERSION,
        azure_endpoint=settings.AZURE_ENDPOINT,
        api_key=settings.AZURE_API_KEY
    )
    
    search_client = SearchClient(settings.SEARCH_ENDPOINT, settings.SEARCH_INDEX, cred)
    
    batch = []
    for chunk in chunks:
        vector = embeddings.embed_query(chunk.page_content)
        batch.append({
            "id": str(uuid.uuid4()),
            "content": chunk.page_content,
            "source": chunk.metadata.get("source", "unknown"),
            "content_vector": vector
        })
        if len(batch) >= 50:
            search_client.upload_documents(batch)
            batch = []
            print(".", end="", flush=True)
            
    if batch: search_client.upload_documents(batch)
    print("\n✅ Ingesta Completada.")

if __name__ == "__main__":
    run_ingest()