import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from ollama import AsyncClient as OllamaAsyncClient
from ollama import Options
from pydantic import BaseModel, ValidationError

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

# Top-level Ollama API parameters that should not be passed as model options.
# These are handled as separate top-level arguments to client.chat() instead.
_OLLAMA_TOP_LEVEL_PARAMS = frozenset({'format', 'stream'})


@dataclass
class ChatOllama(BaseChatModel):
	"""
	A wrapper around Ollama's chat model.
	"""

	model: str

	# # Model params
	# TODO (matic): Why is this commented out?
	# temperature: float | None = None

	# Client initialization parameters
	host: str | None = None
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None
	ollama_options: Mapping[str, Any] | Options | None = None

	# Top-level Ollama API parameters (forwarded as separate args to client.chat())
	format: str | dict[str, Any] | None = None
	stream: bool = False

	# Static
	@property
	def provider(self) -> str:
		return 'ollama'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		return {
			'host': self.host,
			'timeout': self.timeout,
			'client_params': self.client_params,
		}

	def get_client(self) -> OllamaAsyncClient:
		"""
		Returns an OllamaAsyncClient client.
		"""
		return OllamaAsyncClient(host=self.host, timeout=self.timeout, **self.client_params or {})

	@property
	def name(self) -> str:
		return self.model

	def _clean_options(self) -> dict[str, Any]:
		"""
		Filter out top-level API parameters from ollama_options.

		Ollama accepts parameters like ``format`` and ``stream`` as top-level
		arguments to ``client.chat()``, not as part of the ``options`` dict.
		When users pass them inside ``ollama_options`` they are silently
		ignored (or worse, cause unexpected behaviour with some Ollama
		versions).  We strip them here — users who want these params should
		set them as direct attributes on ``ChatOllama`` instead (which now
		has ``format`` and ``stream`` fields that are forwarded correctly).

		Returns:
			A cleaned dict with only valid model options.
		"""
		if not self.ollama_options:
			return {}
		cleaned = dict(self.ollama_options)
		for key in _OLLAMA_TOP_LEVEL_PARAMS:
			if key in cleaned:
				logger.warning(
					'ollama_options contains "%s", which is a top-level Ollama API parameter '
					'and is ignored inside options. Set ChatOllama.%s instead.',
					key,
					key,
				)
				del cleaned[key]
		return cleaned

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def _extract_stream_content(self, response: Any) -> str:
		"""Extract full content from a streaming Ollama response (async generator)."""
		content_parts: list[str] = []
		async for chunk in response:
			if hasattr(chunk, 'message') and chunk.message and chunk.message.content:
				content_parts.append(chunk.message.content)
		return ''.join(content_parts)

	async def _extract_content(self, response: Any) -> str:
		"""Extract content from either a streaming (async generator) or non-streaming response.

		Ollama's AsyncClient.chat() returns:
		- A single ChatResponse when stream=False (default)
		- An async generator yielding ChatResponse chunks when stream=True
		"""
		if self.stream:
			return await self._extract_stream_content(response)
		return response.message.content or ''

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		ollama_messages = OllamaMessageSerializer.serialize_messages(messages)
		options = self._clean_options()
		# Forward top-level API params (format and stream) to client.chat()
		chat_kwargs: dict[str, Any] = {}
		if self.format is not None:
			chat_kwargs['format'] = self.format
		if self.stream:
			chat_kwargs['stream'] = True

		try:
			if output_format is None:
				response = await self.get_client().chat(
					model=self.model,
					messages=ollama_messages,
					options=options,
					**chat_kwargs,
				)

				completion = await self._extract_content(response)
				return ChatInvokeCompletion(completion=completion, usage=None)
			else:
				schema = output_format.model_json_schema()
				# When output_format is provided, format is set to the schema
				# but allow explicit ChatOllama.format to override
				actual_format = chat_kwargs.get('format', schema)

				# Only forward stream kwarg to avoid passing format twice
				stream_kwargs = {k: v for k, v in chat_kwargs.items() if k == 'stream'}
				response = await self.get_client().chat(
					model=self.model,
					messages=ollama_messages,
					format=actual_format,
					options=options,
					**stream_kwargs,
				)

				completion = await self._extract_content(response)
				completion = output_format.model_validate_json(completion)

				return ChatInvokeCompletion(completion=completion, usage=None)

		except ValidationError as e:
			# Provide a clearer error when the model returns invalid/truncated JSON
			truncated_hint = ''
			if 'EOF' in str(e):
				truncated_hint = (
					' The model returned incomplete or truncated JSON. '
					'This can happen with vision models when format=schema is too restrictive. '
					'Try setting use_vision=False for Ollama vision models, or '
					'removing "format" from ollama_options.'
				)
			raise ModelProviderError(
				message=f'Invalid JSON in model response: {e}{truncated_hint}',
				model=self.name,
			) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
