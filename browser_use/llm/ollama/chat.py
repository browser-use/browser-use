from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from ollama import AsyncClient as OllamaAsyncClient
from ollama import Options
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


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

	def _get_usage(self, response: Any) -> ChatInvokeUsage | None:
		"""Build usage info from an Ollama chat response.

		Ollama reports input/output token counts as `prompt_eval_count` and
		`eval_count`. It has no prefix caching, so the cache fields stay None.
		"""
		prompt_tokens = getattr(response, 'prompt_eval_count', None)
		completion_tokens = getattr(response, 'eval_count', None)

		if prompt_tokens is None and completion_tokens is None:
			return None

		prompt_tokens = prompt_tokens or 0
		completion_tokens = completion_tokens or 0

		return ChatInvokeUsage(
			prompt_tokens=prompt_tokens,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=completion_tokens,
			total_tokens=prompt_tokens + completion_tokens,
		)

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		ollama_messages = OllamaMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				response = await self.get_client().chat(
					model=self.model,
					messages=ollama_messages,
					options=self.ollama_options,
				)

				return ChatInvokeCompletion(completion=response.message.content or '', usage=self._get_usage(response))
			else:
				schema = output_format.model_json_schema()

				response = await self.get_client().chat(
					model=self.model,
					messages=ollama_messages,
					format=schema,
					options=self.ollama_options,
				)

				completion = response.message.content or ''
				if output_format is not None:
					completion = output_format.model_validate_json(completion)

				return ChatInvokeCompletion(completion=completion, usage=self._get_usage(response))

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
