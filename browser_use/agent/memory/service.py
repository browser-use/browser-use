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

	def __init__(
		self,
		message_manager: MessageManager,
		llm: BaseChatModel,
		settings: MemorySettings,
	):
		self.message_manager = message_manager
		self.llm = llm
		self.settings = settings
		self._memory_config = self.settings.config or {'vector_store': {'provider': 'faiss'}}
		self.mem0 = Mem0Memory.from_config(config_dict=self._memory_config)

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

		# Filter out messages that are marked as memory in metadata
		messages_to_process = []
		new_messages = []
		for msg in all_messages:
			# Exclude system message and initial messages
			if isinstance(msg, ManagedMessage) and msg.metadata.message_type in set(['init', 'memory']):
				new_messages.append(msg)
			else:
				messages_to_process.append(msg)

		if len(messages_to_process) <= 1:
			logger.info('Not enough non-memory messages to summarize')
			return

		# Create a summary
		summary = self._create([m.message for m in messages_to_process], current_step)

		if not summary:
			logger.warning('Failed to create summary')
			return

		# Replace the summarized messages with the summary
		summary_message = HumanMessage(content=summary)
		summary_tokens = self.message_manager._count_tokens(summary_message)
		summary_metadata = MessageMetadata(tokens=summary_tokens, message_type='memory')

		# Calculate the total tokens being removed
		removed_tokens = sum(m.metadata.tokens for m in messages_to_process)

		# Add the summary message
		new_messages.append(ManagedMessage(message=summary_message, metadata=summary_metadata))

		# Update the history
		self.message_manager.state.history.messages = new_messages
		self.message_manager.state.history.current_tokens -= removed_tokens
		self.message_manager.state.history.current_tokens += summary_tokens

		logger.info(f'Memories summarized: {len(messages_to_process)} messages converted to procedural memory')
		logger.info(f'Token reduction: {removed_tokens - summary_tokens} tokens')

	def _create(self, messages: List[BaseMessage], current_step: int) -> Optional[str]:
		parsed_messages = convert_to_openai_messages(messages)
		try:
			results = self.mem0.add(
				messages=parsed_messages,
				agent_id=self.settings.agent_id,
				llm=self.llm,
				memory_type='procedural_memory',
				metadata={'step': current_step},
			)
			if len(results.get('results', [])):
				return results.get('results', [])[0].get('memory')
			return None
		except Exception as e:
			logger.error(f'Error creating procedural memory: {e}')
			return None
