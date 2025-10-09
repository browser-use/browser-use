from __future__ import annotations

import json
from typing import Any, overload

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SystemMessage,
	ToolCall,
	UserMessage,
)

MessageDict = dict[str, Any]


class MistralMessageSerializer:
	"""Serializer for converting browser-use messages to Mistral messages."""

	# -------- content handling --------------------------------------------------
	@staticmethod
	def _serialize_text_part(part: ContentPartTextParam) -> str:
		return part.text

	@staticmethod
	def _serialize_image_part(part: ContentPartImageParam) -> dict[str, Any]:
		url = part.image_url.url
		# Mistral supports image URLs
		return {'type': 'image_url', 'image_url': url}

	@staticmethod
	def _serialize_content(content: Any) -> str | list[dict[str, Any]]:
		if content is None:
			return ''
		if isinstance(content, str):
			return content
		serialized: list[dict[str, Any]] = []
		for part in content:
			if part.type == 'text':
				serialized.append({'type': 'text', 'text': MistralMessageSerializer._serialize_text_part(part)})
			elif part.type == 'image_url':
				serialized.append(MistralMessageSerializer._serialize_image_part(part))
			elif part.type == 'refusal':
				serialized.append({'type': 'text', 'text': f'[Refusal] {part.refusal}'})
		return serialized

	# -------- Tool-call handling -------------------------------------------------
	@staticmethod
	def _serialize_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
		mistral_tool_calls: list[dict[str, Any]] = []
		for tc in tool_calls:
			mistral_tool_calls.append(
				{
					'id': tc.id,
					'type': 'function',
					'function': {
						'name': tc.function.name,
						'arguments': tc.function.arguments,
					},
				}
			)
		return mistral_tool_calls

	# -------- Single message serialization -------------------------------------------------
	@overload
	@staticmethod
	def serialize(message: UserMessage) -> MessageDict: ...

	@overload
	@staticmethod
	def serialize(message: SystemMessage) -> MessageDict: ...

	@overload
	@staticmethod
	def serialize(message: AssistantMessage) -> MessageDict: ...

	@staticmethod
	def serialize(message: BaseMessage) -> MessageDict:
		if isinstance(message, UserMessage):
			return {
				'role': 'user',
				'content': MistralMessageSerializer._serialize_content(message.content),
			}
		if isinstance(message, SystemMessage):
			return {
				'role': 'system',
				'content': MistralMessageSerializer._serialize_content(message.content),
			}
		if isinstance(message, AssistantMessage):
			msg: MessageDict = {
				'role': 'assistant',
				'content': MistralMessageSerializer._serialize_content(message.content),
			}
			if message.tool_calls:
				msg['tool_calls'] = MistralMessageSerializer._serialize_tool_calls(message.tool_calls)
			return msg
		raise ValueError(f'Unsupported message type: {type(message)}')

	# -------- Message list serialization -------------------------------------------------
	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[MessageDict]:
		return [MistralMessageSerializer.serialize(m) for m in messages]
