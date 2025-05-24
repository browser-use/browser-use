from typing import Any, Literal, Optional, List
from datetime import datetime
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field


class GranularMemoryEntry(BaseModel):
	"""
	Represents a single, atomic piece of information stored in long-term memory.
	"""

	model_config = ConfigDict(
		from_attributes=True, validate_default=True, revalidate_instances='always', validate_assignment=True
	)

	id: str = Field(default_factory=lambda: str(uuid.uuid4()), description='Unique identifier for the memory entry.')
	timestamp: datetime = Field(default_factory=datetime.utcnow, description='Timestamp of when the memory was created/observed.')
	type: Literal[
		'user_preference',
		'page_content_summary',
		'key_finding',
		'action_taken',
		'action_outcome_success',
		'action_outcome_failure',
		'navigation_milestone',
		'agent_reflection',
		'user_instruction',
		'raw_text',  # Added a generic type for simple text storage
	] = Field(description='The type or category of the memory entry.')
	content: str = Field(description='The actual textual content of the memory.')

	agent_id: str = Field(description='Persistent ID for the agent instance this memory belongs to.')
	run_id: str = Field(description='ID for the specific agent execution session during which this memory was created.')
	user_id: Optional[str] = Field(default=None, description='Optional external user ID, if provided for multi-user scenarios.')

	source_url: Optional[str] = Field(default=None, description='URL where the information was found or action occurred.')
	source_element_xpath: Optional[str] = Field(
		default=None, description='XPath to a relevant element on the page, if applicable.'
	)

	relevance_score: Optional[float] = Field(
		default=None, description='Score indicating relevance, if assigned by LLM or retrieval mechanism.'
	)
	keywords: Optional[List[str]] = Field(
		default_factory=list, description='Keywords associated with the memory for filtering/search.'
	)

	associated_action: Optional[dict] = Field(
		default=None, description='If the memory is linked to a specific agent action, its details.'
	)
	confidence: Optional[float] = Field(default=None, description="Agent's confidence in the fact/memory, if applicable.")

	# To allow easy conversion to mem0 metadata
	def to_mem0_metadata(self) -> dict[str, Any]:
		"""Converts relevant fields to a dictionary suitable for mem0 metadata."""
		metadata = {
			'entry_id': self.id,  # Keep our own ID in metadata
			'entry_type': self.type,
			'timestamp': self.timestamp.isoformat(),
			'source_url': self.source_url,
			'source_element_xpath': self.source_element_xpath,
			'relevance_score': self.relevance_score,
			'keywords': self.keywords,
			'associated_action': self.associated_action,
			'confidence': self.confidence,
			'agent_id': self.agent_id,  # Storing agent_id also in metadata for potential filtering in mem0 if needed
			'run_id': self.run_id,
			'user_id': self.user_id,
		}
		return {k: v for k, v in metadata.items() if v is not None}


class MemoryConfig(BaseModel):
	"""Configuration for procedural and granular memory."""

	model_config = ConfigDict(
		from_attributes=True, validate_default=True, revalidate_instances='always', validate_assignment=True
	)

	# Memory settings
	agent_id: str = Field(
		default_factory=lambda: f'bu_agent_{uuid.uuid4().hex[:12]}',
		min_length=1,
		description="Persistent ID for the agent's memory across sessions. Auto-generated if not provided.",
	)
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
		'lancedb',
		'mongodb',
		'redis',
		'memory',
	] = Field(default='faiss', description='The vector store provider to use with Mem0.')

	vector_store_collection_name: str | None = Field(
		default=None,
		description='Optional: Name for the collection/index in the vector store. If None, a default will be generated for local stores or used by Mem0.',
	)

	vector_store_base_path: str = Field(
		default='/tmp/mem0',
		description='Base path for local vector stores like FAISS or Chroma if no specific path is provided in overrides.',
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
		# Common config items that Mem0 often expects inside the provider's 'config'
		provider_specific_config = {'embedding_model_dims': self.embedder_dims}

		# Default collection name handling
		if self.vector_store_collection_name:
			provider_specific_config['collection_name'] = self.vector_store_collection_name
		elif self.vector_store_provider not in ['memory']:  # 'memory' provider might not need/use a collection name
			if self.vector_store_provider in ['faiss', 'chroma']:
				# Default name for local stores often includes dimensions to avoid conflicts
				provider_specific_config['collection_name'] = f'mem0_{self.vector_store_provider}_{self.embedder_dims}'
			else:  # Cloud/server stores typically have user-defined or fixed names
				provider_specific_config['collection_name'] = 'mem0_default_collection'

		# Default path handling for local stores (FAISS, Chroma) if not overridden by user
		if self.vector_store_provider == 'faiss':
			# FAISS needs a 'path'. If not in override, set default.
			if not (self.vector_store_config_override and 'path' in self.vector_store_config_override):
				provider_specific_config['path'] = (
					f'{self.vector_store_base_path}_{self.embedder_dims}_{self.vector_store_provider}'
				)

		elif self.vector_store_provider == 'chroma':
			# Chroma can use 'path' for local or 'host'/'port' for remote.
			# If neither 'path' nor 'host' is in override, set default 'path'.
			if not (
				self.vector_store_config_override
				and ('path' in self.vector_store_config_override or 'host' in self.vector_store_config_override)
			):
				provider_specific_config['path'] = (
					f'{self.vector_store_base_path}_{self.embedder_dims}_{self.vector_store_provider}'
				)

		elif self.vector_store_provider == 'memory':
			# Mem0's in-memory vector store typically only needs embedding_model_dims
			# and doesn't use 'collection_name' or 'path'.
			# We remove collection_name if it was added by the generic default logic.
			provider_specific_config.pop('collection_name', None)

		# Merge user-provided overrides. These can add new keys or overwrite defaults set above.
		if self.vector_store_config_override:
			provider_specific_config.update(self.vector_store_config_override)

		return {
			'provider': self.vector_store_provider,
			'config': provider_specific_config,
		}

	@property
	def full_config_dict(self) -> dict[str, dict[str, Any]]:
		"""Returns the complete configuration dictionary for Mem0."""
		return {
			'embedder': self.embedder_config_dict,
			'llm': self.llm_config_dict,
			'vector_store': self.vector_store_config_dict,
		}
