from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.load import dumpd, load
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

if TYPE_CHECKING:
	from browser_use.agent.views import AgentOutput, PlanningResult


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

	messages: list[BaseMessage] = Field(default_factory=list)
	current_tokens: int = 0

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def add_message(self, message: BaseMessage, tokens: int = 0) -> None:
		"""Add message with metadata to history"""
		self.messages.append(message)
		self.current_tokens += tokens

	def get_messages(self) -> list[BaseMessage]:
		"""Get all messages"""
		return self.messages

	def get_last_message(self) -> BaseMessage:
		"""Get the last message"""
		if not self.messages:
			raise ValueError("No messages in history")
		return self.messages[-1]

	def remove_last_message(self) -> BaseMessage:
		"""Remove the last message"""
		if not self.messages:
			raise ValueError("No messages in history")
		message = self.messages.pop()
		# Get token count from message if available
		token_count = getattr(message, "metadata", {}).get("tokens", 0)
		self.current_tokens -= token_count
		return message

	def remove_last_state_message(self) -> None:
		"""Remove the last state message"""
		for i in range(len(self.messages) - 1, -1, -1):
			if isinstance(self.messages[i], HumanMessage) and "browser_state" in self.messages[i].content:
				self.messages.pop(i)
				break

	def total_tokens(self) -> int:
		"""Get total tokens in history"""
		return self.current_tokens

	def final_result(self) -> str | None:
		"""Get the final result"""
		for message in reversed(self.messages):
			if isinstance(message, AIMessage) and hasattr(message, "content"):
				if isinstance(message.content, str) and "FINAL ANSWER" in message.content:
					parts = message.content.split("FINAL ANSWER")
					if len(parts) > 1:
						return parts[1].strip()
		return None

	def model_dump(self) -> dict:
		"""Get the model dump"""
		return {"messages": [dumpd(m) for m in self.messages], "current_tokens": self.current_tokens}

	@classmethod
	def model_validate(cls, obj: dict) -> MessageHistory:
		"""Validate the model"""
		messages = [load(m) for m in obj["messages"]]
		return cls(messages=messages, current_tokens=obj["current_tokens"])


class MessageManagerState(BaseModel):
	"""Holds the state for MessageManager"""

	history: MessageHistory = Field(default_factory=MessageHistory)
	tool_id: int = 1

	model_config = ConfigDict(arbitrary_types_allowed=True)
