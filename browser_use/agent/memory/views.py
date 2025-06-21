from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field


class MemoryConfig(BaseModel):
	"""Configuration for procedural memory."""

	model_config = ConfigDict(
		from_attributes=True, validate_default=True, revalidate_instances='always', validate_assignment=True
	)

	# Memory settings
	agent_id: str = Field(default='browser_use_agent', min_length=1)
	memory_interval: int = Field(default=10, gt=1, lt=100)

	# Embedder settings
	embedder_provider: Literal['openai', 'gemini', 'ollama', 'huggingface'] = 'huggingface'
	embedder_model: str = Field(min_length=2, default='all-MiniLM-L6-v2')
	embedder_dims: int = Field(default=384, gt=10, lt=10000)

	# LLM settings - the LLM instance can be passed separately
	llm_provider: Literal['langchain'] = 'langchain'
	llm_instance: BaseChatModel | None = None

	# Vector store settings
	vector_store_provider: Literal[
		'faiss',
		'qdrant',
		'pinecone',
		'supabase',
		'elasticsearch',
		'chroma',
		'weaviate',
		'milvus',
		'pgvector',
		'upstash_vector',
		'vertex_ai_vector_search',
		'azure_ai_search',
		'redis',
	] = Field(default='faiss', description='The vector store provider to use with Mem0.')

	vector_store_collection_name: str | None = Field(
		default=None,
		description='Optional: Name for the collection/index in the vector store. If None, a default will be generated for local stores or used by Mem0.',
	)

	vector_store_base_path: str = Field(
		default='/tmp/mem0',
		description='Base path for local vector stores like FAISS, Chroma, or Qdrant (file-based) if no specific path is provided in overrides.',
	)

	vector_store_config_override: dict[str, Any] | None = Field(
		default=None,
		description="Advanced: Override or provide additional config keys that Mem0 expects for the chosen vector_store provider's 'config' dictionary (e.g., host, port, api_key).",
	)

	@property
	def vector_store_path(self) -> str:
		"""Returns the full vector store path for the current configuration. e.g. /tmp/mem0_384_faiss"""
		return f'{self.vector_store_base_path}_{self.embedder_dims}_{self.vector_store_provider}'

	@property
	def embedder_config_dict(self) -> dict[str, Any]:
		"""Returns the embedder configuration dictionary."""
		return {
			'provider': self.embedder_provider,
			'config': {'model': self.embedder_model, 'embedding_dims': self.embedder_dims},
		}

	@property
	def llm_config_dict(self) -> dict[str, Any]:
		"""Returns the LLM configuration dictionary."""
		return {'provider': self.llm_provider, 'config': {'model': self.llm_instance}}

	@property
	def vector_store_config_dict(self) -> dict[str, Any]:
		"""
		Returns the vector store configuration dictionary for Mem0,
		tailored to the selected provider.
		"""
		provider_specific_config: dict[str, Any] = {'embedding_model_dims': self.embedder_dims}

		# --- Default collection_name handling ---
		if self.vector_store_collection_name:
			provider_specific_config['collection_name'] = self.vector_store_collection_name
		else:
			is_local_file_storage_mode = False
			is_qdrant_server_mode = False

			if self.vector_store_provider == 'faiss':
				is_local_file_storage_mode = True
			elif self.vector_store_provider == 'chroma':
				# Chroma is local file mode if not configured with host/port overrides
				if not (
					self.vector_store_config_override
					and ('host' in self.vector_store_config_override or 'port' in self.vector_store_config_override)
				):
					is_local_file_storage_mode = True
			elif self.vector_store_provider == 'qdrant':
				has_path_override = self.vector_store_config_override and 'path' in self.vector_store_config_override
				is_server_configured = self.vector_store_config_override and (
					'host' in self.vector_store_config_override
					or 'port' in self.vector_store_config_override
					or 'url' in self.vector_store_config_override
					or 'api_key' in self.vector_store_config_override
				)
				if has_path_override or not is_server_configured:
					is_local_file_storage_mode = True
				if is_server_configured:  # Can be server even if path is also set for some hybrid qdrant setups
					is_qdrant_server_mode = True

			if is_local_file_storage_mode:
				provider_specific_config['collection_name'] = f'mem0_{self.vector_store_provider}_{self.embedder_dims}'
			elif self.vector_store_provider == 'upstash_vector':
				provider_specific_config['collection_name'] = ''
			elif (
				self.vector_store_provider
				in ['elasticsearch', 'milvus', 'pgvector', 'redis', 'weaviate', 'supabase', 'azure_ai_search']
				or (self.vector_store_provider == 'qdrant' and is_qdrant_server_mode and not is_local_file_storage_mode)
				or (self.vector_store_provider == 'qdrant' and not is_local_file_storage_mode)
			):  # Qdrant in explicit server mode
				provider_specific_config['collection_name'] = 'mem0'
			else:
				# Fallback for providers like Pinecone, VertexAI (where name is usually user-required)
				# or if a new provider is added and not yet handled explicitly.
				provider_specific_config['collection_name'] = 'mem0_default_collection'

		# --- Default path handling for local file-based stores ---
		default_local_path = f'{self.vector_store_base_path}_{self.embedder_dims}_{self.vector_store_provider}'

		if self.vector_store_provider == 'faiss':
			if not (self.vector_store_config_override and 'path' in self.vector_store_config_override):
				provider_specific_config['path'] = default_local_path

		elif self.vector_store_provider == 'chroma':
			# Set default path if Chroma is in local mode and path is not overridden
			is_chroma_server_mode = self.vector_store_config_override and (
				'host' in self.vector_store_config_override or 'port' in self.vector_store_config_override
			)
			path_in_override = self.vector_store_config_override and 'path' in self.vector_store_config_override

			if not is_chroma_server_mode and not path_in_override:
				provider_specific_config['path'] = default_local_path

		elif self.vector_store_provider == 'qdrant':
			# Set default path if Qdrant is in local file mode and path is not overridden
			has_path_override = self.vector_store_config_override and 'path' in self.vector_store_config_override
			is_server_configured = self.vector_store_config_override and (
				'host' in self.vector_store_config_override
				or 'port' in self.vector_store_config_override
				or 'url' in self.vector_store_config_override
				or 'api_key' in self.vector_store_config_override
			)

			if not has_path_override and not is_server_configured:
				provider_specific_config['path'] = default_local_path

		# Merge user-provided overrides. These can add new keys or overwrite defaults set above.
		if self.vector_store_config_override:
			provider_specific_config.update(self.vector_store_config_override)

		return {
			'provider': self.vector_store_provider,
			'config': provider_specific_config,
		}

	@property
	def full_config_dict(self) -> dict[str, Any]:
		"""Returns the complete configuration dictionary for Mem0."""
		return {
			'embedder': self.embedder_config_dict,
			'llm': self.llm_config_dict,
			'vector_store': self.vector_store_config_dict,
		}
