from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Optional, Dict, Any
from langchain_core.language_models.chat_models import BaseChatModel

class MemoryConfig(BaseModel):
	"""Configuration for procedural memory."""
	model_config = ConfigDict(from_attributes=True, validate_default=True, revalidate_instances='always')

	# Memory settings
	agent_id: str = Field(default="browser_use_agent", min_length=1)
	memory_interval: int = Field(default=10, gt=1, lt=100)

	# Embedder settings
	embedder_provider: Literal['openai', 'gemini', 'ollama', 'huggingface'] = 'huggingface'
	embedder_model: str = Field(min_length=2, default='all-MiniLM-L6-v2')
	embedder_dims: int = Field(default=384, gt=10, lt=10000)

	# LLM settings - the LLM instance can be passed separately
	llm_provider: Literal['langchain'] = 'langchain'
	llm_instance: Optional[BaseChatModel] = None

	# Vector store settings
	vector_store_provider: Literal['faiss'] = 'faiss'
	vector_store_path: str = Field(default="/tmp/mem0_384_faiss")

	@property
	def embedder_config_dict(self) -> Dict[str, Any]:
		"""Returns the embedder configuration dictionary."""
		return {
			'provider': self.embedder_provider,
			'config': {
				'model': self.embedder_model,
				'embedding_dims': self.embedder_dims
			}
		}

	@property
	def llm_config_dict(self) -> Dict[str, Any]:
		"""Returns the LLM configuration dictionary."""
		return {
			'provider': self.llm_provider,
			'config': {
				'model': self.llm_instance
			}
		}

	@property
	def vector_store_config_dict(self) -> Dict[str, Any]:
		"""Returns the vector store configuration dictionary."""
		return {
			'provider': self.vector_store_provider,
			'config': {
				'embedding_model_dims': self.embedder_dims,
				'path': f"{self.vector_store_path}_{self.embedder_dims}_faiss"
			}
		}

	@property
	def full_config_dict(self) -> Dict[str, Dict[str, Any]]:
		"""Returns the complete configuration dictionary for Mem0."""
		return {
			'embedder': self.embedder_config_dict,
			'llm': self.llm_config_dict,
			'vector_store': self.vector_store_config_dict,
		}