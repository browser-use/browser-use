import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models
from browser_use.agent.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)

class VectorDB:
    """Generic vector database initialization and management"""
    
    # Class variable to store instances
    _instances: dict[str, 'VectorDB'] = {}
    
    def __init__(
        self,
        collection_name: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        url: str | None = None,
        api_key: str | None = None,
        use_local: bool = False,
        local_path: str = "./local_qdrant"
    ):
        # Initialize Qdrant client
        if use_local:
            self.client = QdrantClient(path=local_path)
            logger.info(f"Using local Qdrant storage at: {local_path}")
        else:
            if not url or not api_key:
                raise ValueError("URL and API key are required for remote Qdrant")
            self.client = QdrantClient(url=url, api_key=api_key)
            logger.info("Using remote Qdrant storage")

        self.collection_name = collection_name
        self.model = EmbeddingModel.get_instance()
        
        # Create collection if it doesn't exist
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        if not any(c.name == self.collection_name for c in collections):
            dimension = self.model.get_sentence_embedding_dimension()
            if dimension is None:
                raise ValueError("Encoder returned None for embedding dimension")
            
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE
                )
            )

    def encode_text(self, text: str) -> list[float]:
        """Encode text into vector embedding"""
        return self.model.encode(text).tolist()

    @classmethod
    def get_instance(
        cls,
        collection_name: str,
        use_local: bool = False,
        local_path: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> 'VectorDB | None':
        """Get or create a VectorDB instance"""
        instance_key = f"{collection_name}:{url if url else local_path}"
        
        if instance_key not in cls._instances:
            try:
                if use_local:
                    if not local_path:
                        logger.warning("Local vector DB enabled but no path provided")
                        return None
                    instance = cls(collection_name=collection_name, use_local=True, local_path=local_path)
                elif url and api_key:
                    instance = cls(collection_name=collection_name, url=url, api_key=api_key)
                else:
                    logger.warning("No valid vector DB configuration provided")
                    return None
                
                cls._instances[instance_key] = instance
                
            except Exception as e:
                logger.warning(f"Failed to initialize vector DB: {e}")
                return None
                
        return cls._instances[instance_key]