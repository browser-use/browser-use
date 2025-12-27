import re
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
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)

# Pattern to detect Qwen 3 VL MoE models (unsupported by llama.cpp/Ollama)
# Matches: qwen3-vl-moe, qwen3vlmoe, qwen-3-vl-moe, qwen3_vl_moe, etc.
QWEN3_VL_MOE_PATTERN = re.compile(r'qwen[-_]?3[-_]?vl[-_]?moe', re.IGNORECASE)


def is_unsupported_qwen_model(model_name: str) -> bool:
	"""
	Check if the model is a known unsupported Qwen architecture.

	Qwen 3 VL MoE models use 'qwen3vlmoe' architecture which is not
	supported by llama.cpp/Ollama at the time of writing.

	See: https://github.com/browser-use/browser-use/issues/3813
	"""
	if not model_name:
		return False
	return bool(QWEN3_VL_MOE_PATTERN.search(model_name))


def get_unsupported_model_message(model_name: str) -> str:
	"""Generate a helpful error message for unsupported models."""
	return (
		f"Model '{model_name}' uses the 'qwen3vlmoe' architecture which is not supported by Ollama/llama.cpp. "
		f'Supported alternatives:\n'
		f"  • Ollama vision models: 'qwen2.5-vl', 'qwen2-vl', 'llava', 'llava-llama3'\n"
		f'  • Cloud providers: Use OpenRouter or ChatBrowserUse for Qwen 3 VL MoE\n'
		f'See: https://github.com/browser-use/browser-use/issues/3813'
	)


@dataclass
class ChatOllama(BaseChatModel):
	"""
	A wrapper around Ollama's chat model.
	"""

	model: str

	# Client initialization parameters
	host: str | None = None
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None
	ollama_options: Mapping[str, Any] | Options | None = None

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

	def _validate_model(self) -> None:
		"""
		Validate the model is supported by Ollama.

		Raises:
			ModelProviderError: If the model architecture is not supported.
		"""
		if is_unsupported_qwen_model(self.model):
			raise ModelProviderError(message=get_unsupported_model_message(self.model), model=self.name)

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		# Pre-validate model architecture
		self._validate_model()

		ollama_messages = OllamaMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				response = await self.get_client().chat(
					model=self.model,
					messages=ollama_messages,
					options=self.ollama_options,
				)

				return ChatInvokeCompletion(completion=response.message.content or '', usage=None)
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

				return ChatInvokeCompletion(completion=completion, usage=None)

		except ModelProviderError:
			# Re-raise our own errors without wrapping
			raise
		except Exception as e:
			error_msg = str(e)

			# Enhance error message for unknown architecture errors
			if 'unknown model architecture' in error_msg.lower():
				error_msg = (
					f'{error_msg}\n\n'
					f'This model architecture is not supported by your local Ollama installation. '
					f'Try using a supported model or a cloud provider.'
				)

			raise ModelProviderError(message=error_msg, model=self.name) from e
