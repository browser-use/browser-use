import uuid
from datetime import datetime, timezone
from typing import Any, Literal

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
	timestamp: datetime = Field(
		default_factory=lambda: datetime.now(timezone.utc), description='Timestamp of when the memory was created/observed.'
	)
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
	user_id: str | None = Field(default=None, description='Optional external user ID, if provided for multi-user scenarios.')

	source_url: str | None = Field(default=None, description='URL where the information was found or action occurred.')
	source_element_xpath: str | None = Field(default=None, description='XPath to a relevant element on the page, if applicable.')

	relevance_score: float | None = Field(
		default=None, description='Score indicating relevance, if assigned by LLM or retrieval mechanism.'
	)
	keywords: list[str] | None = Field(default=None, description='Keywords associated with the memory for filtering/search.')

	associated_action: dict | None = Field(
		default=None, description='If the memory is linked to a specific agent action, its details.'
	)
	confidence: float | None = Field(default=None, description="Agent's confidence in the fact/memory, if applicable.")

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

	# Granular Memory specific settings
	granular_memory_collection_name: str | None = Field(
		default='browser_use_granular_facts',
		description='Name for the collection/index in the vector store dedicated to granular facts. If None, uses default mem0 collection.',
	)

	# Embedder settings
	embedder_provider: Literal['openai', 'gemini', 'ollama', 'huggingface'] = 'huggingface'
	embedder_model: str = Field(min_length=2, default='all-MiniLM-L6-v2')
	embedder_dims: int = Field(default=384, gt=10, lt=10000)

	# LLM settings - the LLM instance can be passed separately
	llm_provider: Literal['langchain'] = 'langchain'
	llm_instance: BaseChatModel | None = (
		None  # Made Optional as it might not be needed if only using for storage/retrieval via mem0 client directly
	)

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
		# Use the main collection name if provided, otherwise generate one.
		# This path is more for local file-based stores like FAISS.
		collection_part = self.vector_store_collection_name or f'default_summaries_{self.embedder_dims}'
		return f'{self.vector_store_base_path}/{self.vector_store_provider}/{collection_part}'

	@property
	def embedder_config_dict(self) -> dict[str, Any]:
		"""Returns the embedder configuration dictionary."""
		return {
			'provider': self.embedder_provider,
			'config': {'model': self.embedder_model, 'embedding_dims': self.embedder_dims},
		}

	@property
	def llm_config_dict(self) -> dict[str, Any]:
		"""Returns the LLM configuration dictionary for Mem0, if LLM instance is provided."""
		if self.llm_instance:
			return {
				'provider': self.llm_provider,
				'config': {'model': self.llm_instance},
			}
		return None

	@property
	def vector_store_config_dict(self) -> dict[str, Any]:
		"""
		Returns the vector store configuration dictionary for Mem0,
		tailored to the selected provider for summary/main memory.
		"""
		# Common config items that Mem0 often expects inside the provider's 'config'
		provider_specific_config = {'embedding_model_dims': self.embedder_dims}

		# Default collection name handling for main/summary memory
		main_collection_name = self.vector_store_collection_name
		if not main_collection_name and self.vector_store_provider not in ['memory']:
			if self.vector_store_provider in ['faiss', 'chroma', 'lancedb']:  # LanceDB added as it is a local store
				main_collection_name = f'mem0_summaries_{self.vector_store_provider}_{self.embedder_dims}'
			else:
				main_collection_name = 'mem0_default_summaries_collection'

		if main_collection_name:
			provider_specific_config['collection_name'] = main_collection_name

		# Default path handling for local stores if not overridden
		if self.vector_store_provider in ['faiss', 'chroma', 'lancedb']:
			default_path_key = 'path'
			if self.vector_store_provider == 'lancedb':
				default_path_key = 'uri'  # LanceDB uses 'uri'

			if not (self.vector_store_config_override and default_path_key in self.vector_store_config_override):
				path_suffix = f'{main_collection_name or "default_collection"}'
				provider_specific_config[default_path_key] = (
					f'{self.vector_store_base_path}/{self.vector_store_provider}/{path_suffix}'
				)
		elif self.vector_store_provider == 'memory':
			provider_specific_config.pop('collection_name', None)

		if self.vector_store_config_override:
			provider_specific_config.update(self.vector_store_config_override)

		return {
			'provider': self.vector_store_provider,
			'config': provider_specific_config,
		}

	@property
	def full_config_dict(self) -> dict[str, Any]:
		"""Returns the complete configuration dictionary for Mem0."""
		config_dict: dict[str, Any] = {  # Use Any for value type
			'embedder': self.embedder_config_dict,
			'vector_store': self.vector_store_config_dict,
		}
		llm_conf = self.llm_config_dict
		if llm_conf:
			config_dict['llm'] = llm_conf
		return config_dict
