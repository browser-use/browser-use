from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

import httpx
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.mistral.schema import MistralSchemaOptimizer
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

logger = logging.getLogger(__name__)
T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatMistral(BaseChatModel):
	"""Mistral /chat/completions wrapper with schema sanitization."""

	model: str = 'mistral-medium-latest'

	# Generation params
	temperature: float | None = 0.2
	top_p: float | None = None
	max_tokens: int | None = 4096  # Mistral expects max_tokens (not max_completion_tokens)
	seed: int | None = None
	safe_prompt: bool = False

	# Client params
	api_key: str | None = None  # Falls back to MISTRAL_API_KEY
	base_url: str | httpx.URL = 'https://api.mistral.ai/v1'
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 5
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None

	@property
	def provider(self) -> str:
		return 'mistral'

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_api_key(self) -> str:
		key = self.api_key or os.getenv('MISTRAL_API_KEY')
		if not key:
			raise ModelProviderError('Missing Mistral API key', status_code=401, model=self.name)
		return key

	def _get_base_url(self) -> str:
		return str(os.getenv('MISTRAL_BASE_URL', self.base_url)).rstrip('/')

	def _auth_headers(self) -> dict[str, str]:
		headers = {
			'Authorization': f'Bearer {self._get_api_key()}',
			'Content-Type': 'application/json',
		}
		if self.default_headers:
			headers.update(self.default_headers)
		return headers

	def _client(self) -> httpx.AsyncClient:
		if self.http_client:
			return self.http_client

		if not hasattr(self, '_cached_client'):
			transport = httpx.AsyncHTTPTransport(retries=self.max_retries)
			client_args: dict[str, Any] = {'transport': transport}
			if self.timeout is not None:
				client_args['timeout'] = self.timeout
			self._cached_client = httpx.AsyncClient(**client_args)
		return self._cached_client

	def _serialize_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
		raw_messages: list[dict[str, Any]] = []
		for msg in OpenAIMessageSerializer.serialize_messages(messages):
			dumper = getattr(msg, 'model_dump', None)
			if callable(dumper):
				raw_messages.append(cast(dict[str, Any], dumper(exclude_none=True)))
			else:
				raw_messages.append(cast(dict[str, Any], msg))  # type: ignore[arg-type]
		return raw_messages

	def _query_params(self) -> dict[str, str] | None:
		if self.default_query is None:
			return None
		return {k: str(v) for k, v in self.default_query.items() if v is not None}

	def _build_usage(self, usage: dict[str, Any] | None) -> ChatInvokeUsage | None:
		if not usage:
			return None

		return ChatInvokeUsage(
			prompt_tokens=usage.get('prompt_tokens', 0),
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=usage.get('completion_tokens', 0),
			total_tokens=usage.get('total_tokens', 0),
		)

	def _extract_content_text(self, choice: dict[str, Any]) -> str:
		message = choice.get('message', {})
		content = message.get('content')

		if isinstance(content, list):
			text_parts = []
			for part in content:
				if isinstance(part, dict):
					if part.get('type') == 'text' and 'text' in part:
						text_parts.append(part.get('text', ''))
					elif 'content' in part:
						text_parts.append(str(part['content']))
			return ''.join(text_parts)

		if isinstance(content, dict):
			return json.dumps(content)

		return content or ''

	def _parse_error(self, response: httpx.Response) -> str:
		try:
			body = response.json()
			if isinstance(body, dict):
				for key in ('message', 'error', 'detail'):
					val = body.get(key)
					if isinstance(val, dict):
						val = val.get('message') or val.get('detail')
					if val:
						return str(val)
		except Exception:
			pass
		return response.text

	async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
		url = f'{self._get_base_url()}/chat/completions'
		client = self._client()
		response = await client.post(url, headers=self._auth_headers(), json=payload, params=self._query_params())

		if response.status_code >= 400:
			message = self._parse_error(response)
			if response.status_code == 429:
				raise ModelRateLimitError(message=message, status_code=response.status_code, model=self.name)
			raise ModelProviderError(message=message, status_code=response.status_code, model=self.name)

		try:
			return response.json()
		except Exception as e:
			raise ModelProviderError(message=f'Failed to parse Mistral response: {e}', model=self.name) from e

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		payload: dict[str, Any] = {
			'model': self.model,
			'messages': self._serialize_messages(messages),
		}

		# Generation params
		if self.temperature is not None:
			payload['temperature'] = self.temperature
		if self.top_p is not None:
			payload['top_p'] = self.top_p
		if self.max_tokens is not None:
			payload['max_tokens'] = self.max_tokens
		if self.seed is not None:
			payload['seed'] = self.seed
		if self.safe_prompt:
			payload['safe_prompt'] = self.safe_prompt

		# Structured output path
		if output_format is not None:
			payload['response_format'] = {
				'type': 'json_schema',
				'json_schema': {
					'name': 'agent_output',
					'strict': True,
					'schema': MistralSchemaOptimizer.create_mistral_compatible_schema(output_format),
				},
			}

		try:
			data = await self._post(payload)
			choices = data.get('choices', [])
			if not choices:
				raise ModelProviderError('Mistral returned no choices', model=self.name)

			content_text = self._extract_content_text(choices[0])
			usage = self._build_usage(data.get('usage'))

			if output_format is None:
				return ChatInvokeCompletion(completion=content_text, usage=usage)

			parsed = output_format.model_validate_json(content_text)
			return ChatInvokeCompletion(completion=parsed, usage=usage)

		except ModelRateLimitError:
			raise
		except ModelProviderError:
			raise
		except Exception as e:
			logger.error(f'Mistral invocation failed: {e}')
			raise ModelProviderError(message=str(e), model=self.name) from e
