from __future__ import annotations

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

	Qwen does not do constrained decoding for an OpenAI-style ``response_format``
	json_schema (it returns valid-but-unconstrained JSON, so deeply nested action
	unions come back mis-shaped). It does, however, follow forced function-call
	argument schemas reliably, so structured output is produced via a single
	forced tool call instead of ``response_format``.

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

			# Structured output via a single forced tool call (Qwen follows this reliably)
			schema = SchemaOptimizer.create_optimized_json_schema(
				output_format,
				remove_min_items=self.remove_min_items_from_schema,
				remove_defaults=self.remove_defaults_from_schema,
			)
			schema.pop('title', None)
			tool_name = output_format.__name__

			response = await self.get_client().chat.completions.create(
				model=self.model,
				messages=openai_messages,
				tools=[
					{
						'type': 'function',
						'function': {
							'name': tool_name,
							'description': f'Return a JSON object of type {tool_name}',
							'parameters': schema,
						},
					}
				],
				tool_choice={'type': 'function', 'function': {'name': tool_name}},
				**model_params,
			)

			choice = response.choices[0]
			tool_calls = choice.message.tool_calls
			if not tool_calls:
				raise ModelProviderError(
					message='Expected a tool call in DashScope response but got none',
					status_code=502,
					model=self.name,
				)

			parsed = output_format.model_validate_json(tool_calls[0].function.arguments)
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
