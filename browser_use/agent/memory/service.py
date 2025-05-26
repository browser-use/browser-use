from __future__ import annotations

import logging
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
)

# Import Mem0Memory with an alias to avoid confusion if needed, though direct use is fine
from mem0 import Memory as Mem0StoreProvider  # Renamed for clarity

from browser_use.agent.memory.views import GranularMemoryEntry, MemoryConfig
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import ManagedMessage, MessageMetadata
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


class Memory:
	"""
	Manages procedural and granular memory for agents.

	This class implements a memory management system using Mem0.
	It can transform agent interaction history into concise, structured representations (procedural memory)
	and also store and retrieve individual, atomic pieces of information (granular facts).
	"""

	def __init__(
		self,
		message_manager: MessageManager,
		llm: BaseChatModel,
		config: MemoryConfig | None = None,
	):
		self.message_manager = message_manager
		self.llm = llm

		# Initialize configuration with defaults based on the LLM if not provided
		if config is None:
			# Set appropriate embedder based on LLM type
			# llm_instance is crucial for procedural memory
			self.config = MemoryConfig(llm_instance=llm)
			llm_class = llm.__class__.__name__
			if llm_class == 'ChatOpenAI':
				self.config.embedder_provider = 'openai'
				self.config.embedder_model = 'text-embedding-3-small'
				self.config.embedder_dims = 1536
			elif llm_class == 'ChatGoogleGenerativeAI':
				self.config.embedder_provider = 'gemini'
				self.config.embedder_model = 'models/text-embedding-004'
				self.config.embedder_dims = 768
			elif llm_class == 'ChatOllama':
				self.config.embedder_provider = 'ollama'
				self.config.embedder_model = 'nomic-embed-text'
				self.config.embedder_dims = 512
		else:
			# Re-validate user-provided config and ensure llm_instance is set if procedural memory is intended
			self.config = MemoryConfig(**dict(config))
			if not self.config.llm_instance and llm:  # If config didn't set an LLM, but one was passed (for procedural)
				self.config.llm_instance = llm

		# Check for required packages
		try:
			# also disable mem0's telemetry when ANONYMIZED_TELEMETRY=False
			if os.getenv('ANONYMIZED_TELEMETRY', 'true').lower()[0] in 'fn0':
				os.environ['MEM0_TELEMETRY'] = 'False'
		except ImportError:
			raise ImportError('mem0 is required when enable_memory=True. Please install it with `pip install mem0ai`.')

		if self.config.embedder_provider == 'huggingface':
			try:
				# check that required package is installed if huggingface is used
				from sentence_transformers import SentenceTransformer  # noqa: F401
			except ImportError:
				raise ImportError(
					'sentence_transformers is required when enable_memory=True and embedder_provider="huggingface". Please install it with `pip install sentence-transformers`.'
				)

		# --- Initialize Mem0 store for Procedural Summaries ---
		self.procedural_mem_store: Mem0StoreProvider | None = None
		if self.config.llm_instance:  # Procedural memory relies on mem0's LLM summarization
			try:
				# Procedural memory uses the main vector_store_config_dict from MemoryConfig
				# which includes self.config.vector_store_collection_name
				procedural_mem0_config_dict = {
					'llm': self.config.llm_config_dict,
					'embedder': self.config.embedder_config_dict,
					'vector_store': self.config.vector_store_config_dict,
				}
				self.procedural_mem_store = Mem0StoreProvider.from_config(config_dict=procedural_mem0_config_dict)
				proc_coll_name = (
					procedural_mem0_config_dict['vector_store']
					.get('config', {})
					.get('collection_name', 'mem0_default_procedural')
				)
				logger.info(
					f"Procedural mem0 store initialized for agent '{self.config.agent_id}' using collection '{proc_coll_name}'."
				)
			except Exception as e:
				logger.error(f"Failed to initialize procedural mem0 store for agent '{self.config.agent_id}': {e}", exc_info=True)
				self.procedural_mem_store = None
		else:
			logger.info('Procedural memory store not initialized as llm_instance is missing in MemoryConfig.')

		# --- Initialize Mem0 store for Granular Facts ---
		self.granular_mem_store: Mem0StoreProvider | None = None
		try:
			# For granular facts, we might use a different collection name.
			# We'll reuse embedder, but vector_store config needs adjustment for collection name.
			# LLM is not strictly required for the granular store if mem0 isn't doing LLM ops on facts.
			granular_vs_config = dict(self.config.vector_store_config_dict)  # Make a mutable copy

			# Determine the collection name for granular facts
			granular_coll_name = self.config.granular_memory_collection_name
			if not granular_coll_name:  # If not explicitly set, generate a default
				if self.config.vector_store_provider in ['faiss', 'chroma', 'lancedb', 'memory']:
					granular_coll_name = f'mem0_granular_{self.config.vector_store_provider}_{self.config.embedder_dims}'
				else:  # For cloud/server stores, a clear name is good.
					granular_coll_name = f'mem0_granular_facts_{self.config.agent_id}'

			granular_vs_config['config']['collection_name'] = granular_coll_name

			# Adjust path for local file-based stores if collection name determines directory
			if self.config.vector_store_provider in ['faiss', 'chroma', 'lancedb']:
				path_key = 'uri' if self.config.vector_store_provider == 'lancedb' else 'path'
				# Only override path if it wasn't explicitly set in vector_store_config_override
				if not (self.config.vector_store_config_override and path_key in self.config.vector_store_config_override):
					granular_vs_config['config'][path_key] = (
						f'{self.config.vector_store_base_path}/{self.config.vector_store_provider}/{granular_coll_name}'
					)

			granular_mem0_config_dict = {
				'embedder': self.config.embedder_config_dict,
				'vector_store': granular_vs_config,
				'llm': self.config.llm_config_dict,
			}
			# Ensure llm_config_dict is not None if an llm instance is available
			if not granular_mem0_config_dict['llm'] and self.config.llm_instance:
				# This case might happen if llm_provider was not 'langchain' or llm_instance was set later.
				# It's good to ensure llm_config_dict is correctly formed if an llm_instance is available in self.config
				granular_mem0_config_dict['llm'] = {
					'provider': self.config.llm_provider,  # Default is 'langchain'
					'config': {'model': self.config.llm_instance},
				}

				# If after all attempts, llm config is still None, and you want to be strict:
			if not granular_mem0_config_dict.get('llm'):
				logger.warning(
					f"Granular mem0 store for agent '{self.config.agent_id}' is being initialized without an LLM. Fact extraction might be limited."
				)
			self.granular_mem_store = Mem0StoreProvider.from_config(config_dict=granular_mem0_config_dict)
			logger.info(
				f"Granular facts mem0 store initialized for agent '{self.config.agent_id}' "
				f"using collection '{granular_coll_name}' "
				f'(LLM configured: {bool(granular_mem0_config_dict.get("llm"))}).'
			)
			if granular_mem0_config_dict.get('llm'):
				logger.debug(f'Granular store LLM config: {granular_mem0_config_dict["llm"]}')
		except Exception as e:
			logger.error(f"Failed to initialize granular facts mem0 store for agent '{self.config.agent_id}': {e}", exc_info=True)
			self.granular_mem_store = None

	@time_execution_sync('--create_procedural_memory')
	def create_procedural_memory(self, current_step: int) -> None:
		"""
		Create a procedural memory if needed based on the current step.

		Args:
		    current_step: The current step number of the agent
		"""
		if not self.procedural_mem_store:
			logger.warning('Procedural memory store not available. Skipping summarization.')
			return
		if not self.config.llm_instance:  # Double check as mem0 will need it
			logger.warning('LLM instance not configured in MemoryConfig. Skipping procedural memory creation.')
			return

		logger.debug(f'Creating procedural memory at step {current_step}')

		# Get all messages
		all_messages = self.message_manager.state.history.messages
		if not isinstance(all_messages, list):  # Should be a list
			logger.error(f'Expected all_messages to be a list, got {type(all_messages)}')
			return

		# Separate messages into those to keep as-is and those to process for memory
		new_messages_for_mm = []  # Messages to keep in message manager's active window

		messages_to_process_for_mem0_dicts = []
		managed_messages_summarized = []  # Keep track of ManagedMessage objects that are summarized

		for managed_msg in all_messages:
			if not isinstance(managed_msg, ManagedMessage):
				logger.warning(f'Item in history is not ManagedMessage: {type(managed_msg)}. Skipping for procedural memory.')
				# Decide if these non-ManagedMessages should be kept or discarded.
				# If they should be kept as-is: new_messages_for_mm.append(managed_msg)
				continue
			if managed_msg.metadata.message_type in {'init', 'memory'}:
				new_messages_for_mm.append(managed_msg)
			else:
				base_msg: BaseMessage = managed_msg.message

				is_content_present = False
				if base_msg.content is not None:
					if isinstance(base_msg.content, str):
						is_content_present = len(base_msg.content.strip()) > 0
					else:  # content could be list of dicts for multimodal
						is_content_present = bool(base_msg.content)

				has_tool_calls = hasattr(base_msg, 'tool_calls') and bool(base_msg.tool_calls)

				if not is_content_present and not has_tool_calls:
					logger.debug(f'Message of type {base_msg.type} has no content or tool calls. Skipping for summarization.')
					continue

				role = ''
				content_for_mem0 = base_msg.content

				if base_msg.type == 'human':
					role = 'user'
				elif base_msg.type == 'ai':
					role = 'assistant'
					if has_tool_calls and base_msg.tool_calls:  # Langchain tool_calls are List[ToolCall]
						tool_calls_str_parts = []
						for tc in base_msg.tool_calls:  # tc is a dict-like ToolCall object
							tc_name = tc.get('name', 'N/A') if isinstance(tc, dict) else getattr(tc, 'name', 'N/A')
							tc_args = tc.get('args', {}) if isinstance(tc, dict) else getattr(tc, 'args', {})
							tc_id = tc.get('id', 'N/A') if isinstance(tc, dict) else getattr(tc, 'id', 'N/A')
							tool_calls_str_parts.append(f"Call tool '{tc_name}' with args {tc_args} (id: {tc_id})")
						tool_calls_description = 'Requested tool calls: ' + '; '.join(tool_calls_str_parts)
						content_for_mem0 = (
							(str(base_msg.content) + '\n' + tool_calls_description)
							if is_content_present and base_msg.content
							else tool_calls_description
						)
				elif base_msg.type == 'system':
					role = 'system'
				elif base_msg.type == 'tool':  # ToolMessage
					role = 'system'  # Represent tool results as system messages for mem0
					content_for_mem0 = f"Tool result for call ID '{getattr(base_msg, 'tool_call_id', 'N/A')}': {base_msg.content}"

				if role:
					messages_to_process_for_mem0_dicts.append({'role': role, 'content': content_for_mem0})
					managed_messages_summarized.append(managed_msg)
				else:
					logger.debug(
						f"Skipping message type '{base_msg.type}' for procedural memory summarization as role mapping is not defined."
					)

		# Need at least 2 messages to create a meaningful summary
		if len(messages_to_process_for_mem0_dicts) <= 1:
			logger.debug('Not enough processable messages to summarize for mem0')
			return

		try:
			logger.debug(
				f'Sending {len(messages_to_process_for_mem0_dicts)} message dicts to procedural_mem_store.add for agent {self.config.agent_id}'
			)
			mem0_response = self.procedural_mem_store.add(  # Renamed for clarity
				messages=messages_to_process_for_mem0_dicts,
				user_id=self.config.agent_id,
				metadata={'step': current_step, 'memory_type': 'procedural_summary'},
			)

			logger.debug(f'Mem0 response for procedural memory (agent {self.config.agent_id}): {mem0_response}')

			memory_content_strings = []

			if isinstance(mem0_response, dict) and 'results' in mem0_response:
				results_list = mem0_response.get('results', [])
				if isinstance(results_list, list):
					for res_item in results_list:
						if isinstance(res_item, dict) and res_item.get('memory', '').strip():
							memory_content_strings.append(res_item['memory'])
			elif isinstance(mem0_response, list):  # Fallback if it directly returns a list
				for res_item in mem0_response:
					if isinstance(res_item, dict) and res_item.get('memory', '').strip():
						memory_content_strings.append(res_item['memory'])
			else:
				logger.warning(
					f'Unexpected response type from procedural_mem_store.add for agent {self.config.agent_id}: {type(mem0_response)}. Response: {mem0_response}'
				)

			if not memory_content_strings:
				logger.warning(
					f'Failed to extract procedural memory content strings from mem0 response for agent {self.config.agent_id}.'
				)
				return

			memory_content = ' '.join(memory_content_strings)
			if not memory_content.strip():
				logger.warning(f'Procedural memory content from mem0 for agent {self.config.agent_id} is empty after joining.')
				return

			logger.info(
				f'Successfully created procedural memory content for agent {self.config.agent_id}: {memory_content[:100]}...'
			)
			memory_message_obj = HumanMessage(content=memory_content)
			memory_tokens = self.message_manager._count_tokens(memory_message_obj)
			memory_metadata = MessageMetadata(tokens=memory_tokens, message_type='memory')

			removed_tokens = sum(msg.metadata.tokens for msg in managed_messages_summarized)

			new_messages_for_mm.append(ManagedMessage(message=memory_message_obj, metadata=memory_metadata))

			self.message_manager.state.history.messages = new_messages_for_mm
			self.message_manager.state.history.current_tokens -= removed_tokens
			self.message_manager.state.history.current_tokens += memory_tokens
			logger.info(
				f'Procedural memory created for agent {self.config.agent_id}: {len(messages_to_process_for_mem0_dicts)} original messages consolidated.'
			)

		except Exception as e:
			logger.error(f'Error during procedural memory creation for agent {self.config.agent_id}: {e}', exc_info=True)

	@time_execution_sync('--add_granular_fact')
	def add_granular_fact(self, fact: GranularMemoryEntry) -> str | None:
		"""
		Adds a single granular fact to the long-term memory using the `granular_mem_store`.

		Args:
			fact: The GranularMemoryEntry object to store.
				`fact.agent_id` should match `self.config.agent_id` for consistency.
				`fact.run_id` identifies the current session.

		Returns:
		    The ID of the stored memory entry from mem0, or None if failed.
		"""
		if not self.granular_mem_store:
			logger.error(
				f'Granular memory store not available for agent {self.config.agent_id}. Cannot add fact: {fact.content[:50]}...'
			)
			return None
		if not isinstance(fact, GranularMemoryEntry):
			logger.error(f'Invalid fact type for add_granular_fact: {type(fact)}')
			return None
		if fact.agent_id != self.config.agent_id:
			logger.warning(
				f"Mismatch: Fact agent_id '{fact.agent_id}' differs from MemoryConfig agent_id '{self.config.agent_id}'. Using fact's agent_id for mem0 user_id."
			)

		# For mem0, the "message" is the core content to be embedded and searched.
		# Prepare metadata, ensuring 'categories' is correctly structured for mem0 search.
		# The search functionality expects a 'categories' key in metadata with a list of strings.
		mem0_metadata = fact.to_mem0_metadata()
		if 'categories' not in mem0_metadata:
			mem0_metadata['categories'] = [fact.type]
		elif not isinstance(mem0_metadata['categories'], list):
			mem0_metadata['categories'] = [mem0_metadata['categories']]

		content_to_add_to_mem0 = [{'role': 'user', 'content': f'Fact Type: {fact.type}. Details: {fact.content}'}]
		infer_setting = False  # Instruct mem0 to store this content as-is

		try:
			mem0_response = self.granular_mem_store.add(
				content_to_add_to_mem0,  # Pass as a list of messages
				user_id=fact.agent_id,  # user_id in mem0 context
				metadata=mem0_metadata,
				infer=infer_setting,  # Key to prevent LLM-based sub-fact extraction
			)

			logger.debug(
				f'Mem0 call `add_granular_fact` for agent {fact.agent_id} '
				f"with content_to_add='{str(content_to_add_to_mem0)[:100]}...', infer={infer_setting} "
				f'returned: {mem0_response}'
			)

			actual_results = []
			# mem0.add with a list of messages (even one) and infer=False should still return a list of dicts,
			# where each dict corresponds to a message processed.
			if isinstance(mem0_response, list):
				actual_results = mem0_response
			elif isinstance(mem0_response, dict) and 'results' in mem0_response:  # Some mem0 versions might wrap in 'results'
				actual_results = mem0_response.get('results', [])

			if actual_results and isinstance(actual_results, list) and len(actual_results) > 0:
				first_item = actual_results[0]  # Since we're adding one "fact message"
				if isinstance(first_item, dict) and 'id' in first_item:
					logger.info(
						f'Successfully added granular fact to mem0 for agent {fact.agent_id}. '
						f'Mem0 ID: {first_item.get("id")}. Content: {fact.content[:100]}...'
					)
					return first_item.get('id')
				else:
					logger.warning(
						f'Mem0 add_granular_fact for agent {fact.agent_id} returned list/results, '
						f'but the first item is not a dict with an "id" or is malformed: {first_item}'
					)
					return None

			logger.warning(
				f'Mem0 add_granular_fact for agent {fact.agent_id} did not return a valid ID or an empty list. '
				f'Result from mem0.add: {mem0_response}'
			)
			return None
		except Exception as e:
			logger.error(f'Failed to add granular fact to mem0 for agent {fact.agent_id}: {e}', exc_info=True)
			return None

	@time_execution_sync('--search_granular_facts')
	def search_granular_facts(
		self,
		query: str,
		agent_id: str,  # The agent_id whose memory we are searching (mem0 user_id)
		run_id: str | None = None,
		fact_types: list[str] | None = None,
		source_url: str | None = None,
		keywords: list[str] | None = None,
		limit: int = 5,
		# threshold: float = 0.1,
	) -> list[dict]:
		"""
		Searches for granular facts in the long-term memory using the `granular_mem_store`.

		Args:
		    query: The search query string.
		    agent_id: The persistent ID of the agent whose memory to search. Used as user_id in mem0.
		    run_id: Optional. Filter memories by a specific agent execution session (via metadata).
		    fact_types: Optional. List of fact types (mem0 categories) to filter by.
		    source_url: Optional. Filter memories by a specific source URL (via metadata).
		    keywords: Optional. List of keywords to filter by (via metadata).
		    limit: Maximum number of results to return.

		Returns:
		    A list of search result dictionaries from mem0, each typically containing 'id', 'memory', 'metadata', 'score', etc.
		"""
		if not self.granular_mem_store:
			logger.error(f'Granular memory store not available for agent {agent_id}. Cannot search facts.')
			return []
		# Construct v2 filter conditions
		v2_filter_conditions = []
		if run_id:
			v2_filter_conditions.append({'metadata.run_id': run_id})
		if source_url:
			v2_filter_conditions.append({'metadata.source_url': source_url})
		if keywords:
			# OR logic for multiple keywords: matches if any specified keyword is present
			or_keyword_conditions = [{'metadata.keywords': {'contains': kw}} for kw in keywords]
			if or_keyword_conditions:
				v2_filter_conditions.append({'OR': or_keyword_conditions})
		if fact_types:
			if len(fact_types) == 1:
				v2_filter_conditions.append({'metadata.entry_type': fact_types[0]})
			elif len(fact_types) > 1:
				v2_filter_conditions.append({'metadata.entry_type': {'in': fact_types}})

		final_v2_filters = None
		if v2_filter_conditions:
			if len(v2_filter_conditions) == 1:
				final_v2_filters = {'AND': v2_filter_conditions}
			elif len(v2_filter_conditions) > 1:
				final_v2_filters = {'AND': v2_filter_conditions}

		try:
			search_kwargs = {
				'query': query,
				'user_id': agent_id,
				'limit': limit,
				# 'threshold': threshold,  # Pass the threshold
			}
			if final_v2_filters:
				search_kwargs['filters'] = final_v2_filters

			logger.debug(f'Mem0 search_granular_facts for agent {agent_id} with kwargs: {search_kwargs}')

			search_results_data = self.granular_mem_store.search(**search_kwargs)
			results = search_results_data.get('results', []) if isinstance(search_results_data, dict) else []

			logger.debug(
				f"Searched granular facts for agent {agent_id} with query '{query[:50]}...'. "
				f'Filters used: {search_kwargs.get("filters")}. Version: {search_kwargs.get("version")}. '
				f'Found {len(results)} results.'
			)
			return results
		except Exception as e:
			logger.error(f'Failed to search granular facts in mem0 for agent {agent_id}: {e}', exc_info=True)
			return []
