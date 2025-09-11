from __future__ import annotations

import json
import os
from typing import Any, TypeVar, overload

from openai import APIConnectionError, APIStatusError, RateLimitError
from openai.types.chat import ChatCompletionContentPartTextParam
from openai.types.shared_params.response_format_json_schema import (
	JSONSchema,
	ResponseFormatJSONSchema,
)
from pydantic import BaseModel, ValidationError

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

_DEFAULT_BASE_URL = 'https://api.mistral.ai/v1'

T = TypeVar('T', bound=BaseModel)


class ChatMistral(ChatOpenAI):
	"""Mistral provider using the OpenAI-compatible chat API.

	This is a thin wrapper around the OpenAI-compatible client with sensible
	defaults for Mistral. All functionality (streaming, tool-calling, retries,
	structured output) is inherited from ChatOpenAI.
	"""

	def __init__(
		self,
		model: str = 'mistral-medium-latest',
		api_key: str | None = None,
		base_url: str | None = None,
		max_tokens: int | None = None,
		**kwargs: Any,
	) -> None:
		api_key = api_key or os.getenv('MISTRAL_API_KEY')
		if not api_key:
			raise ValueError('Mistral API key missing: set MISTRAL_API_KEY or pass api_key=')

		base_url = base_url or os.getenv('MISTRAL_BASE_URL', _DEFAULT_BASE_URL)

		# Mistral does not accept OpenAI's `max_completion_tokens`.
		# Avoid sending it by default to prevent 422 errors.
		kwargs.setdefault('max_completion_tokens', None)

		super().__init__(model=model, api_key=api_key, base_url=base_url, **kwargs)
		# Store Mistral-specific token limit option
		self.max_tokens = max_tokens

	@property
	def provider(self) -> str:  # type: ignore[override]
		# Identify provider explicitly for logs/metrics, while keeping OpenAI compatibility.
		return 'mistral'

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages, translating `max_tokens` for Mistral.
		Mirrors ChatOpenAI.ainvoke but avoids `max_completion_tokens` and uses `max_tokens` instead.
		"""
		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)

		try:
			model_params: dict[str, Any] = {}

			if self.temperature is not None:
				model_params['temperature'] = self.temperature

			if self.frequency_penalty is not None:
				model_params['frequency_penalty'] = self.frequency_penalty

			# Use Mistral's parameter name
			if self.max_tokens is not None:
				model_params['max_tokens'] = self.max_tokens

			if self.top_p is not None:
				model_params['top_p'] = self.top_p

			if self.seed is not None:
				model_params['seed'] = self.seed

			if self.service_tier is not None:
				model_params['service_tier'] = self.service_tier

			if self.reasoning_models and any(str(m).lower() in str(self.model).lower() for m in self.reasoning_models):
				model_params['reasoning_effort'] = self.reasoning_effort
				# Avoid OpenAI-specific knobs for reasoning models
				model_params.pop('temperature', None)
				model_params.pop('frequency_penalty', None)

			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					**model_params,
				)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
				)

			else:
				# Build JSON schema and patch unsupported keywords for Mistral
				raw_schema = SchemaOptimizer.create_optimized_json_schema(output_format)

				# Remove keywords Mistral rejects in json_schema (observed errors):
				# - minLength
				# - maxLength
				# - pattern
				# - format
				unsupported = {'minLength', 'maxLength', 'pattern', 'format'}

				def _strip_unsupported(obj: object) -> object:
					if isinstance(obj, dict):
						return {k: _strip_unsupported(v) for k, v in obj.items() if k not in unsupported}
					elif isinstance(obj, list):
						return [_strip_unsupported(v) for v in obj]
					return obj

				clean_schema = _strip_unsupported(raw_schema)

				response_format_schema: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': clean_schema,  # type: ignore[assignment]
				}

				# Optionally include schema text in the system prompt to guide structure
				if self.add_schema_to_system_prompt and openai_messages and openai_messages[0]['role'] == 'system':
					schema_text = f'\n<json_schema>\n{response_format_schema}\n</json_schema>'
					if isinstance(openai_messages[0]['content'], str):
						openai_messages[0]['content'] += schema_text
					elif isinstance(openai_messages[0]['content'], list):
						openai_messages[0]['content'] = list(openai_messages[0]['content']) + [
							ChatCompletionContentPartTextParam(text=schema_text, type='text')
						]

				# Request structured response with patched schema
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					response_format=ResponseFormatJSONSchema(
						json_schema=response_format_schema,
						type='json_schema',
					),
					**model_params,
				)

				if response.choices[0].message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)

				usage = self._get_usage(response)

				try:
					parsed = output_format.model_validate_json(response.choices[0].message.content)
				except ValidationError:
					# Fallback: some Mistral responses wrap the JSON object in a list
					try:
						data = json.loads(response.choices[0].message.content)
						if isinstance(data, list) and data:
							first = data[0]
							if isinstance(first, dict):
								parsed = output_format.model_validate(first)
							else:
								raise
						else:
							raise
					except Exception as e:
						raise ModelProviderError(message=str(e), model=self.name) from e

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
				)

		except RateLimitError as e:
			# Mirror ChatOpenAI behavior to preserve status codes and messages
			try:
				error_message = e.response.json().get('error', {})
				error_message = (
					error_message.get('message', 'Unknown model error') if isinstance(error_message, dict) else error_message
				)
			except Exception:
				error_message = str(e)
			raise ModelProviderError(
				message=error_message,
				status_code=getattr(e.response, 'status_code', None),
				model=self.name,
			) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			try:
				error_message = e.response.json().get('error', {})
			except Exception:
				error_message = e.response.text
			error_message = (
				error_message.get('message', 'Unknown model error') if isinstance(error_message, dict) else error_message
			)
			raise ModelProviderError(
				message=error_message,
				status_code=e.response.status_code,
				model=self.name,
			) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
