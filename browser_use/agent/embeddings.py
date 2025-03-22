from sentence_transformers import SentenceTransformer

class EmbeddingModel:
    _instance = None
    _model = None

    @classmethod
    def get_instance(cls) -> SentenceTransformer:
        """Get or create the sentence transformer model instance"""
        if cls._model is None:
            cls._model = SentenceTransformer('all-MiniLM-L6-v2')
        return cls._model 