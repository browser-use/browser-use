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


class ZhipuAIMessageSerializer:
	"""Serializer for converting browser-use messages to ZhipuAI / Z.ai messages."""

	# -------- content serialization -----------------------------------------
	@staticmethod
	def _serialize_text_part(part: ContentPartTextParam) -> str:
		return part.text

	@staticmethod
	def _serialize_image_part(part: ContentPartImageParam) -> dict[str, Any]:
		url = part.image_url.url
		return {'type': 'image_url', 'image_url': {'url': url}}

	@staticmethod
	def _serialize_content(content: Any) -> str | list[dict[str, Any]]:
		if content is None:
			return ''
		if isinstance(content, str):
			return content
		serialized: list[dict[str, Any]] = []
		for part in content:
			if part.type == 'text':
				serialized.append({'type': 'text', 'text': ZhipuAIMessageSerializer._serialize_text_part(part)})
			elif part.type == 'image_url':
				serialized.append(ZhipuAIMessageSerializer._serialize_image_part(part))
			elif part.type == 'refusal':
				serialized.append({'type': 'text', 'text': f'[Refusal] {part.refusal}'})
		return serialized

	# -------- Tool-call serialization ----------------------------------------
	@staticmethod
	def _serialize_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
		zhipuai_tool_calls: list[dict[str, Any]] = []
		for tc in tool_calls:
			try:
				arguments = json.loads(tc.function.arguments)
			except json.JSONDecodeError:
				arguments = {'arguments': tc.function.arguments}
			zhipuai_tool_calls.append(
				{
					'id': tc.id,
					'type': 'function',
					'function': {
						'name': tc.function.name,
						'arguments': json.dumps(arguments),
					},
				}
			)
		return zhipuai_tool_calls

	# -------- Single message serialization -----------------------------------
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
				'content': ZhipuAIMessageSerializer._serialize_content(message.content),
			}
		if isinstance(message, SystemMessage):
			return {
				'role': 'system',
				'content': ZhipuAIMessageSerializer._serialize_content(message.content),
			}
		if isinstance(message, AssistantMessage):
			content = ZhipuAIMessageSerializer._serialize_content(message.content)
			if message.refusal:
				if content:
					content = f'{content}\n[Refusal] {message.refusal}'
				else:
					content = f'[Refusal] {message.refusal}'
			msg: MessageDict = {
				'role': 'assistant',
				'content': content,
			}
			if message.tool_calls:
				msg['tool_calls'] = ZhipuAIMessageSerializer._serialize_tool_calls(message.tool_calls)
			return msg
		raise ValueError(f'Unknown message type: {type(message)}')

	# -------- List serialization --------------------------------------------
	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[MessageDict]:
		return [ZhipuAIMessageSerializer.serialize(m) for m in messages]
