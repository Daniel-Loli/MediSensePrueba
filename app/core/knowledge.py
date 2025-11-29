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