from __future__ import annotations

import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
)
from langchain_core.messages.utils import convert_to_openai_messages

from browser_use.agent.memory.views import MemoryConfig
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import ManagedMessage, MessageMetadata
from browser_use.config import CONFIG
from browser_use.utils import time_execution_sync


class Memory:
	"""
	Manages procedural memory for agents.

	This class implements a procedural memory management system using Mem0 that transforms agent interaction history
	into concise, structured representations at specified intervals. It serves to optimize context window
	utilization during extended task execution by converting verbose historical information into compact,
	yet comprehensive memory constructs that preserve essential operational knowledge.
	"""

	def __init__(
		self,
		message_manager: MessageManager,
		llm: BaseChatModel,
		config: MemoryConfig | None = None,
		logger: logging.Logger | None = None,
	):
		self.message_manager = message_manager
		self.llm = llm
		self.logger = logger or logging.getLogger(__name__)

		# Initialize configuration with defaults based on the LLM if not provided
		if config is None:
			self.config = MemoryConfig(llm_instance=llm, agent_id=f'agent_{id(self)}')

			# Set appropriate embedder based on LLM type
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
			# Ensure LLM instance is set in the config
			self.config = MemoryConfig.model_validate(config)  # revalidate using Pydantic
			self.config.llm_instance = llm

		# Check for required packages
		try:
			# also disable mem0's telemetry when ANONYMIZED_TELEMETRY=False
			if not CONFIG.ANONYMIZED_TELEMETRY:
				os.environ['MEM0_TELEMETRY'] = 'False'
			from mem0 import Memory as Mem0Memory
		except ImportError:
			raise ImportError('mem0 is required when enable_memory=True. Please install it with `pip install mem0`.')

		if self.config.embedder_provider == 'huggingface':
			try:
				# check that required package is installed if huggingface is used
				from sentence_transformers import SentenceTransformer  # noqa: F401 # type: ignore
			except ImportError:
				raise ImportError(
					'sentence_transformers is required when enable_memory=True and embedder_provider="huggingface". Please install it with `pip install sentence-transformers`.'
				)

		# Initialize Mem0 with the configuration
		with warnings.catch_warnings():
			warnings.filterwarnings('ignore', category=DeprecationWarning)
			try:
				self.mem0 = Mem0Memory.from_config(config_dict=self.config.full_config_dict)
			except Exception as e:
				if 'history_old' in str(e) and 'sqlite3.OperationalError' in str(type(e)):
					# Handle the migration error by using a unique history database path
					import tempfile
					import uuid

					self.logger.warning(
						f'⚠️ Mem0 SQLite migration error detected in {self.config.full_config_dict}. Using a temporary database to avoid conflicts.\n{type(e).__name__}: {e}'
					)
					# Create a unique temporary database path
					temp_dir = tempfile.gettempdir()
					unique_id = str(uuid.uuid4())[:8]
					history_db_path = os.path.join(temp_dir, f'browser_use_mem0_history_{unique_id}.db')

					# Add the history_db_path to the config
					config_with_history_path = self.config.full_config_dict.copy()
					config_with_history_path['history_db_path'] = history_db_path

					# Try again with the new config
					self.mem0 = Mem0Memory.from_config(config_dict=config_with_history_path)
				else:
					# Re-raise if it's a different error
					raise

	@time_execution_sync('--create_procedural_memory')
	def create_procedural_memory(self, current_step: int) -> None:
		"""
		Create a procedural memory if needed based on the current step.

		Args:
		    current_step: The current step number of the agent
		"""
		self.logger.debug(f'📜 Creating procedural memory at step {current_step}')

		# Get all messages
		all_messages = self.message_manager.state.history.messages

		# Separate messages into those to keep as-is and those to process for memory
		new_messages = []
		messages_to_process = []

		for msg in all_messages:
			if isinstance(msg, ManagedMessage) and msg.metadata.message_type in {'init', 'memory'}:
				# Keep system and memory messages as they are
				new_messages.append(msg)
			else:
				if len(msg.message.content) > 0:
					messages_to_process.append(msg)

		# Need at least 2 messages to create a meaningful summary
		if len(messages_to_process) <= 1:
			self.logger.debug('📜 Not enough non-memory messages to summarize')
			return
		# Create a procedural memory with timeout
		try:
			with ThreadPoolExecutor(max_workers=1) as executor:
				future = executor.submit(self._create, [m.message for m in messages_to_process], current_step)
				memory_content = future.result(timeout=5)
		except TimeoutError:
			self.logger.warning('📜 Procedural memory creation timed out after 30 seconds')
			return
		except Exception as e:
			self.logger.error(f'📜 Error during procedural memory creation: {e}')
			return

		if not memory_content:
			self.logger.warning('📜 Failed to create procedural memory')
			return

		# Replace the processed messages with the consolidated memory
		memory_message = HumanMessage(content=memory_content)
		memory_tokens = self.message_manager._count_tokens(memory_message)
		memory_metadata = MessageMetadata(tokens=memory_tokens, message_type='memory')

		# Calculate the total tokens being removed
		removed_tokens = sum(m.metadata.tokens for m in messages_to_process)

		# Add the memory message
		new_messages.append(ManagedMessage(message=memory_message, metadata=memory_metadata))

		# Update the history
		self.message_manager.state.history.messages = new_messages
		self.message_manager.state.history.current_tokens -= removed_tokens
		self.message_manager.state.history.current_tokens += memory_tokens
		self.logger.info(f'📜 History consolidated: {len(messages_to_process)} steps converted to long-term memory')

	def _create(self, messages: list[BaseMessage], current_step: int) -> str | None:
		parsed_messages = convert_to_openai_messages(messages)
		try:
			results = self.mem0.add(
				messages=parsed_messages,
				agent_id=self.config.agent_id,
				memory_type='procedural_memory',
				metadata={'step': current_step},
			)
			if len(results.get('results', [])):
				return results.get('results', [])[0].get('memory')
			return None
		except Exception as e:
			self.logger.error(f'📜 Error creating procedural memory: {e}')
			return None
