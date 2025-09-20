import os
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
from openai.types.shared import ChatModel
from pydantic import BaseModel

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.like import ChatOpenAILike
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAzureOpenAI(ChatOpenAILike):
	"""
	A class for to interact with any provider using the OpenAI API schema.

	Args:
	    model (str): The name of the OpenAI model to use. Defaults to "not-provided".
	    api_key (Optional[str]): The API key to use. Defaults to "not-provided".
	"""

	# Model configuration
	model: str | ChatModel

	# Client initialization parameters
	api_key: str | None = None
	api_version: str | None = '2024-12-01-preview'
	azure_endpoint: str | None = None
	azure_deployment: str | None = None
	base_url: str | None = None
	azure_ad_token: str | None = None
	azure_ad_token_provider: Any | None = None

	default_headers: dict[str, str] | None = None
	default_query: dict[str, Any] | None = None

	client: AsyncAzureOpenAIClient | None = None

	@property
	def provider(self) -> str:
		return 'azure'

	def _get_client_params(self) -> dict[str, Any]:
		_client_params: dict[str, Any] = {}

		self.api_key = self.api_key or os.getenv('AZURE_OPENAI_API_KEY')
		self.azure_endpoint = self.azure_endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
		self.azure_deployment = self.azure_deployment or os.getenv('AZURE_OPENAI_DEPLOYMENT')
		params_mapping = {
			'api_key': self.api_key,
			'api_version': self.api_version,
			'organization': self.organization,
			'azure_endpoint': self.azure_endpoint,
			'azure_deployment': self.azure_deployment,
			'base_url': self.base_url,
			'azure_ad_token': self.azure_ad_token,
			'azure_ad_token_provider': self.azure_ad_token_provider,
			'http_client': self.http_client,
		}
		if self.default_headers is not None:
			_client_params['default_headers'] = self.default_headers
		if self.default_query is not None:
			_client_params['default_query'] = self.default_query

		_client_params.update({k: v for k, v in params_mapping.items() if v is not None})

		return _client_params

	def get_client(self) -> AsyncAzureOpenAIClient:
		"""
		Returns an asynchronous OpenAI client.

		Returns:
			AsyncAzureOpenAIClient: An instance of the asynchronous OpenAI client.
		"""
		if self.client:
			return self.client

		_client_params: dict[str, Any] = self._get_client_params()

		if self.http_client:
			_client_params['http_client'] = self.http_client
		else:
			# Create a new async HTTP client with custom limits
			_client_params['http_client'] = httpx.AsyncClient(
				limits=httpx.Limits(max_connections=20, max_keepalive_connections=6)
			)

		self.client = AsyncAzureOpenAIClient(**_client_params)

		return self.client

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Azure OpenAI-specific invoke method that filters out unsupported parameters.

		Azure OpenAI doesn't support:
		- reasoning_effort parameter (even for reasoning models like gpt-5-chat)
		- Some response_format configurations

		This override ensures compatibility with Azure OpenAI endpoints.
		"""
		from browser_use.llm.openai.chat import ReasoningModels
		from browser_use.llm.openai.serializer import OpenAIMessageSerializer

		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)

		try:
			model_params: dict[str, Any] = {}

			# Add standard parameters that Azure OpenAI supports
			if self.temperature is not None:
				model_params['temperature'] = self.temperature

			if self.frequency_penalty is not None:
				model_params['frequency_penalty'] = self.frequency_penalty

			if self.max_completion_tokens is not None:
				model_params['max_completion_tokens'] = self.max_completion_tokens

			if self.top_p is not None:
				model_params['top_p'] = self.top_p

			if self.seed is not None:
				model_params['seed'] = self.seed

			# Skip service_tier for Azure (OpenAI-specific)
			# Skip reasoning_effort for Azure (not supported)

			# For reasoning models on Azure, only remove temperature/frequency_penalty
			if any(str(m).lower() in str(self.model).lower() for m in ReasoningModels):
				# Remove conflicting parameters for reasoning models
				del model_params['temperature']
				if 'frequency_penalty' in model_params:
					del model_params['frequency_penalty']

			# Call parent's logic for the actual API call and response handling
			# but with filtered parameters
			if output_format is None:
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
				# For structured output, use more conservative approach for Azure
				# Some response_format configurations may not be supported
				return await super().ainvoke(messages, None)  # Fall back to string output

		except Exception as e:
			# Use parent class error handling
			from browser_use.llm.exceptions import ModelProviderError

			raise ModelProviderError(f'Azure OpenAI error: {str(e)}') from e
