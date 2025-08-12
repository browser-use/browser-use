
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from ollama import AsyncClient as OllamaAsyncClient
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion
import json, re

T = TypeVar('T', bound=BaseModel)

@dataclass

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

	@property
	def provider(self) -> str:
		return 'ollama'

	def _get_client_params(self) -> dict[str, Any]:
		# Bundle client params for Ollama
		return {
			'host': self.host,
			'timeout': self.timeout,
			'client_params': self.client_params,
		}

	def get_client(self) -> OllamaAsyncClient:
		return OllamaAsyncClient(host=self.host, timeout=self.timeout, **self.client_params or {})

	@property
	def name(self) -> str:
		return self.model

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		# For gpt-oss, we have to extract structured output ourselves
		ollama_messages = OllamaMessageSerializer.serialize_messages(messages)
		try:
			response = await self.get_client().chat(
				model=self.model,
				messages=ollama_messages,
				**({'format': output_format.model_json_schema()} if output_format is not None and not self.model.startswith("gpt-oss") else {})
			)
			content = response.message.content or ''
			# gpt-oss needs manual structured output handling
			if output_format is not None and self.model.startswith("gpt-oss"):
				
				processed = content.strip()
				if not processed.startswith('{'):
					json_match = re.search(r'\{.*\}', processed, re.DOTALL)
					if json_match:
						processed = json_match.group(0)
				try:
					parsed_json = json.loads(processed)
					structured_output = output_format.model_validate(parsed_json)
					return ChatInvokeCompletion(completion=structured_output, usage=None)
				except Exception:
					return ChatInvokeCompletion(completion=content, usage=None)
			elif output_format is not None and not self.model.startswith("gpt-oss"):
				completion = output_format.model_validate_json(content)
				return ChatInvokeCompletion(completion=completion, usage=None)
			else:
				return ChatInvokeCompletion(completion=content, usage=None)
		except Exception as e:
			# Always wrap errors so we know which model failed
			raise ModelProviderError(message=str(e), model=self.name) from e
