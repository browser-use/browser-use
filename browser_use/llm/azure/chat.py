import os
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, RateLimitError
from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
from openai.types.responses import Response
from openai.types.shared import ChatModel
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.like import ChatOpenAILike
from browser_use.llm.openai.responses_serializer import ResponsesAPIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


# List of models that only support the Responses API
RESPONSES_API_ONLY_MODELS: list[str] = [
	'gpt-5.1-codex',
	'gpt-5.1-codex-mini',
	'gpt-5.1-codex-max',
	'gpt-5-codex',
	'codex-mini-latest',
	'computer-use-preview',
]


@dataclass
class ChatAzureOpenAI(ChatOpenAILike):
	"""
	A class for to interact with any provider using the OpenAI API schema.

	Args:
	    model (str): The name of the OpenAI model to use. Defaults to "not-provided".
	    api_key (Optional[str]): The API key to use. Defaults to "not-provided".
	    use_responses_api (bool): If True, use the Responses API instead of Chat Completions API.
	        This is required for certain models like gpt-5.1-codex-mini on Azure OpenAI with
	        api_version >= 2025-03-01-preview. Set to 'auto' to automatically detect based on model.
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

	# Responses API support
	use_responses_api: bool | str = 'auto'  # True, False, or 'auto'

	client: AsyncAzureOpenAIClient | None = None

	@property
	def provider(self) -> str:
		return 'azure'

	def _get_client_params(self) -> dict[str, Any]:
		_client_params: dict[str, Any] = {}

		self.api_key = self.api_key or os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY')
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

	def _should_use_responses_api(self) -> bool:
		"""Determine if the Responses API should be used based on model and settings."""
		if isinstance(self.use_responses_api, bool):
			return self.use_responses_api

		# Auto-detect: use Responses API for models that require it
		model_lower = str(self.model).lower()
		for responses_only_model in RESPONSES_API_ONLY_MODELS:
			if responses_only_model.lower() in model_lower:
				return True
		return False

	def _get_usage_from_responses(self, response: Response) -> ChatInvokeUsage | None:
		"""Extract usage information from a Responses API response."""
		if response.usage is None:
			return None

		# Get cached tokens from input_tokens_details if available
		cached_tokens = None
		if response.usage.input_tokens_details is not None:
			cached_tokens = getattr(response.usage.input_tokens_details, 'cached_tokens', None)

		return ChatInvokeUsage(
			prompt_tokens=response.usage.input_tokens,
			prompt_cached_tokens=cached_tokens,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=response.usage.output_tokens,
			total_tokens=response.usage.total_tokens,
		)

	async def _ainvoke_responses_api(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model using the Responses API.

		This is used for models that require the Responses API (e.g., gpt-5.1-codex-mini)
		or when use_responses_api is explicitly set to True.
		"""
		# Serialize messages to Responses API input format
		input_messages = ResponsesAPIMessageSerializer.serialize_messages(messages)

		try:
			model_params: dict[str, Any] = {
				'model': self.model,
				'input': input_messages,
			}

			if self.temperature is not None:
				model_params['temperature'] = self.temperature

			if self.max_completion_tokens is not None:
				model_params['max_output_tokens'] = self.max_completion_tokens

			if self.top_p is not None:
				model_params['top_p'] = self.top_p

			if self.service_tier is not None:
				model_params['service_tier'] = self.service_tier

			# Handle reasoning models
			if self.reasoning_models and any(str(m).lower() in str(self.model).lower() for m in self.reasoning_models):
				# For reasoning models, use reasoning parameter instead of reasoning_effort
				model_params['reasoning'] = {'effort': self.reasoning_effort}
				model_params.pop('temperature', None)

			if output_format is None:
				# Return string response
				response = await self.get_client().responses.create(**model_params)

				usage = self._get_usage_from_responses(response)
				return ChatInvokeCompletion(
					completion=response.output_text or '',
					usage=usage,
					stop_reason=response.status if response.status else None,
				)

			else:
				# For structured output, use the text.format parameter
				json_schema = SchemaOptimizer.create_optimized_json_schema(
					output_format,
					remove_min_items=self.remove_min_items_from_schema,
					remove_defaults=self.remove_defaults_from_schema,
				)

				model_params['text'] = {
					'format': {
						'type': 'json_schema',
						'name': 'agent_output',
						'strict': True,
						'schema': json_schema,
					}
				}

				# Add JSON schema to system prompt if requested
				if self.add_schema_to_system_prompt and input_messages and input_messages[0].get('role') == 'system':
					schema_text = f'\n<json_schema>\n{json_schema}\n</json_schema>'
					content = input_messages[0].get('content', '')
					if isinstance(content, str):
						input_messages[0]['content'] = content + schema_text
					elif isinstance(content, list):
						input_messages[0]['content'] = list(content) + [{'type': 'input_text', 'text': schema_text}]
					model_params['input'] = input_messages

				if self.dont_force_structured_output:
					# Remove the text format parameter if not forcing structured output
					model_params.pop('text', None)

				response = await self.get_client().responses.create(**model_params)

				if not response.output_text:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)

				usage = self._get_usage_from_responses(response)
				parsed = output_format.model_validate_json(response.output_text)

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
					stop_reason=response.status if response.status else None,
				)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages.

		This method routes to either the Responses API or the Chat Completions API
		based on the model and settings.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""
		if self._should_use_responses_api():
			return await self._ainvoke_responses_api(messages, output_format, **kwargs)
		else:
			# Use the parent class implementation (Chat Completions API)
			return await super().ainvoke(messages, output_format, **kwargs)
