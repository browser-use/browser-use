import json
from typing import overload

from langchain_core.messages import (  # pyright: ignore
	AIMessage,
	HumanMessage,
	SystemMessage,
)
from langchain_core.messages import (  # pyright: ignore
	ToolCall as LangChainToolCall,
)
from langchain_core.messages.base import BaseMessage as LangChainBaseMessage  # pyright: ignore

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartRefusalParam,
	ContentPartTextParam,
	ToolCall,
	UserMessage,
)
from browser_use.llm.messages import (
	SystemMessage as BrowserUseSystemMessage,
)


class LangChainMessageSerializer:
	"""Serializer for converting between browser-use message types and LangChain message types."""

	@staticmethod
	def _serialize_user_content(
		content: str | list[ContentPartTextParam | ContentPartImageParam],
	) -> str | list[str | dict]:
		"""Convert user message content for LangChain compatibility."""
		if isinstance(content, str):
			return content

		serialized_parts = []
		for part in content:
			if part.type == 'text':
				serialized_parts.append(
					{
						'type': 'text',
						'text': part.text,
					}
				)
			elif part.type == 'image_url':
				# LangChain format for images
				serialized_parts.append(
					{'type': 'image_url', 'image_url': {'url': part.image_url.url, 'detail': part.image_url.detail}}
				)

		return serialized_parts

	@staticmethod
	def _serialize_system_content(
		content: str | list[ContentPartTextParam],
	) -> str:
		"""Convert system message content to text string for LangChain compatibility."""
		if isinstance(content, str):
			return content

		text_parts = []
		for part in content:
			if part.type == 'text':
				text_parts.append(part.text)

		return '\n'.join(text_parts)

	@staticmethod
	def _serialize_assistant_content(
		content: str | list[ContentPartTextParam | ContentPartRefusalParam] | None,
	) -> str:
		"""Convert assistant message content to text string for LangChain compatibility."""
		if content is None:
			return ''
		if isinstance(content, str):
			return content

		text_parts = []
		for part in content:
			if part.type == 'text':
				text_parts.append(part.text)
			# elif part.type == 'refusal':
			# 	# Include refusal content as text
			# 	text_parts.append(f'[Refusal: {part.refusal}]')

		return '\n'.join(text_parts)

	@staticmethod
	def _serialize_tool_call(tool_call: ToolCall) -> LangChainToolCall:
		"""Convert browser-use ToolCall to LangChain ToolCall."""
		# Parse the arguments string to a dict for LangChain
		try:
			args_dict = json.loads(tool_call.function.arguments)
		except json.JSONDecodeError:
			# If parsing fails, wrap in a dict
			args_dict = {'arguments': tool_call.function.arguments}

		return LangChainToolCall(
			name=tool_call.function.name,
			args=args_dict,
			id=tool_call.id,
		)

	# region - Serialize overloads
	@overload
	@staticmethod
	def serialize(message: UserMessage) -> HumanMessage: ...

	@overload
	@staticmethod
	def serialize(message: BrowserUseSystemMessage) -> SystemMessage: ...

	@overload
	@staticmethod
	def serialize(message: AssistantMessage) -> AIMessage: ...

	@staticmethod
	def serialize(message: BaseMessage) -> LangChainBaseMessage:
		"""Serialize a browser-use message to a LangChain message."""

		if isinstance(message, UserMessage):
			content = LangChainMessageSerializer._serialize_user_content(message.content)
			return HumanMessage(content=content, name=message.name)

		elif isinstance(message, BrowserUseSystemMessage):
			content = LangChainMessageSerializer._serialize_system_content(message.content)
			return SystemMessage(content=content, name=message.name)

		elif isinstance(message, AssistantMessage):
			# Handle content
			content = LangChainMessageSerializer._serialize_assistant_content(message.content)

			# For simplicity, we'll ignore tool calls in LangChain integration
			# as requested by the user
			return AIMessage(
				content=content,
				name=message.name,
			)

		else:
			raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[LangChainBaseMessage]:
		"""Serialize a list of browser-use messages to LangChain messages."""
		return [LangChainMessageSerializer.serialize(m) for m in messages]
