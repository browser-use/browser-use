from typing import Any

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SystemMessage,
	UserMessage,
)


class LiteLLMMessageSerializer:
	@staticmethod
	def _serialize_user_content(
		content: str | list[ContentPartTextParam | ContentPartImageParam],
	) -> str | list[dict[str, Any]]:
		if isinstance(content, str):
			return content

		parts: list[dict[str, Any]] = []
		for part in content:
			if part.type == 'text':
				parts.append(
					{
						'type': 'text',
						'text': part.text,
					}
				)
			elif part.type == 'image_url':
				parts.append(
					{
						'type': 'image_url',
						'image_url': {
							'url': part.image_url.url,
							'detail': part.image_url.detail,
						},
					}
				)
		return parts

	@staticmethod
	def _serialize_system_content(
		content: str | list[ContentPartTextParam],
	) -> str | list[dict[str, Any]]:
		if isinstance(content, str):
			return content

		return [
			{
				'type': 'text',
				'text': p.text,
			}
			for p in content
		]

	@staticmethod
	def _serialize_assistant_content(
		content: str | list[Any] | None,
	) -> str | list[dict[str, Any]] | None:
		if content is None:
			return None
		if isinstance(content, str):
			return content

		parts = []
		for part in content:
			if part.type == 'text':
				parts.append(
					{
						'type': 'text',
						'text': part.text,
					}
				)
			elif part.type == 'refusal':
				parts.append(
					{
						'type': 'text',
						'text': f'[Refusal] {part.refusal}',
					}
				)
		return parts

	@staticmethod
	def serialize(messages: list[BaseMessage]) -> list[dict[str, Any]]:
		result: list[dict[str, Any]] = []
		for msg in messages:
			if isinstance(msg, UserMessage):
				d: dict[str, Any] = {'role': 'user'}
				d['content'] = LiteLLMMessageSerializer._serialize_user_content(msg.content)
				if msg.name is not None:
					d['name'] = msg.name
				result.append(d)

			elif isinstance(msg, SystemMessage):
				d = {'role': 'system'}
				d['content'] = LiteLLMMessageSerializer._serialize_system_content(msg.content)
				if msg.name is not None:
					d['name'] = msg.name
				result.append(d)

			elif isinstance(msg, AssistantMessage):
				d = {'role': 'assistant'}
				d['content'] = LiteLLMMessageSerializer._serialize_assistant_content(msg.content)
				if msg.name is not None:
					d['name'] = msg.name
				if msg.tool_calls:
					d['tool_calls'] = [
						{
							'id': tc.id,
							'type': 'function',
							'function': {
								'name': tc.function.name,
								'arguments': tc.function.arguments,
							},
						}
						for tc in msg.tool_calls
					]
				result.append(d)
		return result
