from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, RateLimitError
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatDashScope(ChatOpenAI):
	"""Alibaba DashScope (Qwen) wrapper via the OpenAI-compatible endpoint.

	Structured output uses ``response_format`` json_schema. Newer Qwen models
	(qwen3.x, qwen-omni, qwen3-vl) enforce it correctly, including nested arrays.
	Forced function-calling is avoided: some of these models reject a forced
	``tool_choice``, and others return nested array fields as stringified JSON.

	The API key is read from ``DASHSCOPE_API_KEY`` when not passed explicitly
	(the OpenAI SDK would otherwise look for OPENAI_API_KEY).
	"""

	model: str = 'qwen-max'
	base_url: str | httpx.URL | None = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

	def __post_init__(self) -> None:
		if self.api_key is None:
			self.api_key = os.environ.get('DASHSCOPE_API_KEY')

	@property
	def provider(self) -> str:
		return 'dashscope'

	def _model_params(self) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if self.temperature is not None:
			params['temperature'] = self.temperature
		if self.frequency_penalty is not None:
			params['frequency_penalty'] = self.frequency_penalty
		if self.max_completion_tokens is not None:
			params['max_completion_tokens'] = self.max_completion_tokens
		if self.top_p is not None:
			params['top_p'] = self.top_p
		if self.seed is not None:
			params['seed'] = self.seed
		return params

	@staticmethod
	def _extract_json_payload(content: str) -> str:
		"""Return the first JSON object/array from a structured DashScope response."""
		text = content.strip()
		if text.startswith('```'):
			lines = text.splitlines()
			if lines and lines[0].lstrip().startswith('```'):
				lines = lines[1:]
			if lines and lines[-1].strip().startswith('```'):
				lines = lines[:-1]
			text = '\n'.join(lines).strip()

		starts = [(i, ch) for i, ch in ((text.find('{'), '{'), (text.find('['), '[')) if i != -1]
		if not starts:
			return text
		start, opener = min(starts, key=lambda item: item[0])
		closer = '}' if opener == '{' else ']'
		depth = 0
		in_string = False
		escape = False
		for idx in range(start, len(text)):
			ch = text[idx]
			if in_string:
				if escape:
					escape = False
				elif ch == '\\':
					escape = True
				elif ch == '"':
					in_string = False
				continue
			if ch == '"':
				in_string = True
			elif ch == opener:
				depth += 1
			elif ch == closer:
				depth -= 1
				if depth == 0:
					return text[start : idx + 1]
		return text

	@classmethod
	def _parse_structured_content(cls, output_format: type[T], content: str) -> T:
		payload = cls._extract_json_payload(content)
		try:
			return output_format.model_validate_json(payload)
		except Exception:
			data = json.loads(payload)
			if isinstance(data, list) and len(data) == 1:
				data = data[0]
			return output_format.model_validate(data)

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)
		model_params = self._model_params()

		try:
			# Plain text output
			if output_format is None:
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					**model_params,
				)
				choice = response.choices[0]
				return ChatInvokeCompletion(
					completion=choice.message.content or '',
					usage=self._get_usage(response),
					stop_reason=choice.finish_reason,
				)

			# Structured output via response_format json_schema (the agent prompt already
			# instructs JSON output, which Qwen requires for this mode).
			schema = SchemaOptimizer.create_optimized_json_schema(
				output_format,
				remove_min_items=self.remove_min_items_from_schema,
				remove_defaults=self.remove_defaults_from_schema,
			)
			schema.pop('title', None)

			response = await self.get_client().chat.completions.create(
				model=self.model,
				messages=openai_messages,
				response_format={
					'type': 'json_schema',
					'json_schema': {'name': output_format.__name__, 'strict': True, 'schema': schema},
				},
				**model_params,
			)

			choice = response.choices[0]
			content = choice.message.content
			if not content:
				raise ModelProviderError(
					message='Expected structured content in DashScope response but got none',
					status_code=502,
					model=self.name,
				)

			parsed = self._parse_structured_content(output_format, content)
			return ChatInvokeCompletion(
				completion=parsed,
				usage=self._get_usage(response),
				stop_reason=choice.finish_reason,
			)

		except ModelProviderError:
			raise
		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e
		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
