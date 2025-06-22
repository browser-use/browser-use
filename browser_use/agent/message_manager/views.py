from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)

if TYPE_CHECKING:
	from browser_use.agent.views import AgentOutput


SupportedMessageTypes = Literal['init', 'memory']


class MessageMetadata(BaseModel):
	"""Metadata for a message"""

	tokens: int = 0
	message_type: SupportedMessageTypes | None = None


class ManagedMessage(BaseModel):
	"""A message with its metadata"""

	message: BaseMessage
	metadata: MessageMetadata = Field(default_factory=MessageMetadata)


class MessageHistory(BaseModel):
	"""History of messages with metadata"""

	messages: list[ManagedMessage] = Field(default_factory=list)
	current_tokens: int = 0

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def add_message(self, message: BaseMessage, metadata: MessageMetadata, position: int | None = None) -> None:
		"""Add message with metadata to history"""
		if position is None:
			self.messages.append(ManagedMessage(message=message, metadata=metadata))
		else:
			self.messages.insert(position, ManagedMessage(message=message, metadata=metadata))
		self.current_tokens += metadata.tokens

	def add_model_output(self, output: AgentOutput) -> None:
		"""Add model output as AI message"""

		msg = AssistantMessage(
			content=output.model_dump_json(),
		)
		self.add_message(msg, MessageMetadata(tokens=100))  # Estimate tokens for tool calls

	def get_messages(self) -> list[BaseMessage]:
		"""Get all messages"""
		return [m.message for m in self.messages]

	def get_total_tokens(self) -> int:
		"""Get total tokens in history"""
		return self.current_tokens

	def remove_oldest_message(self) -> None:
		"""Remove oldest non-system message"""
		for i, msg in enumerate(self.messages):
			if not isinstance(msg, SystemMessage):
				# self.current_tokens -= msg.metadata.tokens
				# TODO: FIX TOKENS
				self.messages.pop(i)
				break

	def remove_last_state_message(self) -> None:
		"""Remove last state message from history"""
		if len(self.messages) > 2 and isinstance(self.messages[-1], UserMessage):
			# self.current_tokens -= self.messages[-1].metadata.tokens
			# TODO: FIX TOKENS
			self.messages.pop()


class MessageManagerState(BaseModel):
	"""Holds the state for MessageManager"""

	history: MessageHistory = Field(default_factory=MessageHistory)
	tool_id: int = 1

	model_config = ConfigDict(arbitrary_types_allowed=True)
