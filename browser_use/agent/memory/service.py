from __future__ import annotations

import logging
from typing import List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
)
from langchain_core.messages.utils import convert_to_openai_messages
from mem0 import Memory as Mem0Memory
from pydantic import BaseModel

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import ManagedMessage, MessageMetadata
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


class MemorySettings(BaseModel):
	"""Settings for procedural memory."""

	agent_id: str
	interval: int = 10
	config: Optional[dict] | None = None


class Memory:
	"""
	Manages procedural memory for agents.

	This class implements a procedural memory management system using Mem0 that transforms agent interaction history
	into concise, structured representations at specified intervals. It serves to optimize context window
	utilization during extended task execution by converting verbose historical information into compact,
	yet comprehensive memory constructs that preserve essential operational knowledge.
	"""

	# Default configuration values as class constants
	DEFAULT_VECTOR_STORE = {'provider': 'faiss', 'config': {'embedding_model_dims': 384}}
	DEFAULT_EMBEDDER = {'provider': 'huggingface', 'config': {'model': 'all-MiniLM-L6-v2'}}

	def __init__(
		self,
		message_manager: MessageManager,
		llm: BaseChatModel,
		settings: MemorySettings,
	):
		self.message_manager = message_manager
		self.llm = llm
		self.settings = settings

		# Create the memory configuration
		self._memory_config = settings.config or self._create_memory_config(llm)

		# Initialize Mem0
		self.mem0 = Mem0Memory.from_config(config_dict=self._memory_config)
		self.mem0.custom_fact_extraction_prompt = self._get_fact_extraction_prompt()

	def _create_memory_config(self, llm: BaseChatModel) -> dict:
		"""
		Create a Mem0 configuration based on the LLM type.

		Args:
			llm: The language model being used by the agent
		Returns:
			dict: A complete Mem0 configuration
		"""
		llm_provider = self._get_llm_provider(llm)
		model_name = self._get_model_name(llm)
		config = {
			'vector_store': Memory.DEFAULT_VECTOR_STORE,
			'llm': {'provider': llm_provider, 'config': {'model': model_name}},
			'embedder': Memory.DEFAULT_EMBEDDER,
		}

		return config

	def _get_model_name(self, llm: BaseChatModel) -> str:
		"""
		Get the model name for the given LLM.
		"""
		model_name = 'Unknown'
		if hasattr(llm, 'model_name'):
			model = llm.model_name  # type: ignore
			model_name = model if model is not None else 'Unknown'
		elif hasattr(llm, 'model'):
			model = llm.model  # type: ignore
			model_name = model if model is not None else 'Unknown'
		if isinstance(model_name, str) and model_name.startswith('model/'):
			model_name = model_name[6:]
		return model_name

	def _get_llm_provider(self, llm: BaseChatModel) -> str:
		"""
		Determine the appropriate Mem0 provider for the given LLM.

		Args:
			llm: The language model to analyze

		Returns:
			str: The provider name
		"""
		# Check the type of LLM and set the appropriate provider
		llm_class_name = llm.__class__.__name__

		if 'GoogleGenerativeAI' in llm_class_name:
			return 'gemini'
		elif 'OpenAI' in llm_class_name:
			if 'Azure' in llm_class_name:
				return 'azure_openai'
			else:
				return 'openai'
		elif 'Anthropic' in llm_class_name:
			return 'anthropic'
		elif 'Groq' in llm_class_name:
			return 'groq'
		elif 'Together' in llm_class_name:
			return 'together'
		elif 'Bedrock' in llm_class_name:
			return 'aws_bedrock'
		elif 'DeepSeek' in llm_class_name:
			return 'deepseek'
		elif 'LMStudio' in llm_class_name:
			return 'lmstudio'

		# If we couldn't determine the provider, log a warning
		logger.warning(f'Could not determine Mem0 provider for LLM type: {llm_class_name}. Using default configuration.')
		return ''

	@staticmethod
	def _get_default_config(llm: BaseChatModel) -> dict:
		"""Returns the default configuration for memory."""
		return {
			'vector_store': Memory.DEFAULT_VECTOR_STORE,
			'llm': {'provider': 'langchain', 'config': {'model': llm}},
			'embedder': Memory.DEFAULT_EMBEDDER,
		}

	@time_execution_sync('--create_procedural_memory')
	def create_procedural_memory(self, current_step: int) -> None:
		"""
		Create a procedural memory if needed based on the current step.

		Args:
		    current_step: The current step number of the agent
		"""
		logger.info(f'Creating procedural memory at step {current_step}')

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
			logger.info('Not enough non-memory messages to summarize')
			return
		# Create a procedural memory
		memory_content = self._create([m.message for m in messages_to_process], current_step)

		if not memory_content:
			logger.warning('Failed to create procedural memory')
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
		logger.info(f'Messages consolidated: {len(messages_to_process)} messages converted to procedural memory')

	def _create(self, messages: List[BaseMessage], current_step: int) -> Optional[str]:
		parsed_messages = convert_to_openai_messages(messages)
		try:
			results = self.mem0.add(
				messages=parsed_messages,
				agent_id=self.settings.agent_id,
				memory_type='procedural_memory',
				metadata={'step': current_step},
			)
			if len(results.get('results', [])):
				return results.get('results', [])[0].get('memory')
			return None
		except Exception as e:
			logger.error(f'Error creating procedural memory: {e}')
			return None

	def _get_fact_extraction_prompt(self) -> str:
		"""
		Get the fact extraction prompt
		"""
		return """You are an AI Agent's Memory System responsible for extracting and storing key information from web browsing sessions. Your task is to process the agent's observations and extract important facts, details, and insights that would be valuable to remember for future reference.

Types of Information to Extract:
1. Key content from webpages (headlines, product details, important text)
2. Data points and statistics encountered during browsing
3. Search results and their relevance
4. Navigation paths and website structures
5. User interface elements and their functions
6. Error messages or obstacles encountered
7. Temporal information (dates, times, durations)
8. Spatial information (layouts, positions, relationships between elements)

Here are some examples:

Input: Clicked on "Products" menu and found 5 categories: Electronics, Clothing, Home, Beauty, and Food.
Output: {"facts": ["The Products menu contains 5 categories", "The categories are Electronics, Clothing, Home, Beauty, and Food"]}

Input: Search for "machine learning courses" returned 15 results. Top result was "Stanford CS229: Machine Learning" with 4.9 star rating.
Output: {"facts": ["Search for 'machine learning courses' returned 15 results", "Top result was Stanford CS229: Machine Learning", "Stanford CS229 has a 4.9 star rating"]}

Input: Product page shows iPhone 13 costs $799, available in 5 colors, with 128GB storage minimum.
Output: {"facts": ["iPhone 13 costs $799", "iPhone 13 is available in 5 colors", "iPhone 13 has minimum 128GB storage"]}

Input: Article headline: "OpenAI's models 'memorized' copyrighted content, new study suggests"
Output: {"facts": ["Study suggests OpenAI's models memorized copyrighted content", "The finding comes from a new study about AI models"]}

Input: Login attempt failed with message "Invalid credentials. Please try again."
Output: {"facts": ["Login attempt failed", "Error message indicated invalid credentials"]}

Guidelines:
- Focus on objective, factual information that would be useful to recall later
- Prioritize specific details over general observations
- Preserve important numerical data (prices, quantities, ratings, etc.)
- Maintain context about what was observed and where
- Break complex observations into discrete, searchable facts
- Format each fact as a complete, standalone statement
- If the content contains no relevant information to remember, return an empty list

Return the extracted facts in JSON format with a "facts" key containing an array of strings.
"""
