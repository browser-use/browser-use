from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.load import dumpd, load
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

if TYPE_CHECKING:
	from browser_use.agent.views import AgentOutput


class MessageMetadata(BaseModel):
	"""Metadata for a message"""

	tokens: int = 0


class ManagedMessage(BaseModel):
	"""A message with its metadata"""

	message: BaseMessage
	metadata: MessageMetadata = Field(default_factory=MessageMetadata)

	model_config = ConfigDict(arbitrary_types_allowed=True)

	# https://github.com/pydantic/pydantic/discussions/7558
	@model_serializer(mode='wrap')
	def to_json(self, original_dump):
		"""
		Returns the JSON representation of the model.

		It uses langchain's `dumps` function to serialize the `message`
		property before encoding the overall dict with json.dumps.
		"""
		data = original_dump(self)

		# NOTE: We override the message field to use langchain JSON serialization.
		data['message'] = dumpd(self.message)

		return data

	@model_validator(mode='before')
	@classmethod
	def validate(
		cls,
		value: Any,
		*,
		strict: bool | None = None,
		from_attributes: bool | None = None,
		context: Any | None = None,
	) -> Any:
		"""
		Custom validator that uses langchain's `loads` function
		to parse the message if it is provided as a JSON string.
		"""
		if isinstance(value, dict) and 'message' in value:
			# NOTE: We use langchain's load to convert the JSON string back into a BaseMessage object.
			value['message'] = load(value['message'])
		return value


class MessageHistory(BaseModel):
	"""History of messages with metadata"""

	messages: list[ManagedMessage] = Field(default_factory=list)
	total_tokens: int = 0

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def add_message(self, message: BaseMessage, metadata: MessageMetadata, position: int = -1) -> None:
		"""Add message with metadata to history"""
		if position == -1:
			self.messages.append(ManagedMessage(message=message, metadata=metadata))
		else:
			self.messages.insert(position, ManagedMessage(message=message, metadata=metadata))
		self.total_tokens += metadata.tokens

	def add_model_output(self, output: 'AgentOutput') -> None:
		"""Add model output as AI message"""
		tool_calls = [
			{
				'name': 'AgentOutput',
				'args': output.model_dump(mode='json', exclude_unset=True),
				'id': '1',
				'type': 'tool_call',
			}
		]

		msg = AIMessage(
			content='',
			tool_calls=tool_calls,
		)
		self.add_message(msg, MessageMetadata(tokens=100))  # Estimate tokens for tool calls

		# Empty tool response
		tool_message = ToolMessage(content='', tool_call_id='1')
		self.add_message(tool_message, MessageMetadata(tokens=10))  # Estimate tokens for empty response

	def get_messages(self) -> list[BaseMessage]:
		"""Get all messages"""
		return [m.message for m in self.messages]

	def get_total_tokens(self) -> int:
		"""Get total tokens in history"""
		return self.total_tokens

	def remove_oldest_message(self) -> None:
		"""Remove oldest non-system message"""
		for i, msg in enumerate(self.messages):
			if not isinstance(msg.message, SystemMessage):
				self.total_tokens -= msg.metadata.tokens
				self.messages.pop(i)
				break

	def remove_last_state_message(self) -> None:
		"""Remove last state message from history"""
		if len(self.messages) > 2 and isinstance(self.messages[-1].message, HumanMessage):
			self.total_tokens -= self.messages[-1].metadata.tokens
			self.messages.pop()


class MessageManagerState(BaseModel):
	"""Holds the state for MessageManager"""

	history: MessageHistory = Field(default_factory=MessageHistory)
	tool_id: int = 1

	model_config = ConfigDict(arbitrary_types_allowed=True)
