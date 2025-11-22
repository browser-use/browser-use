import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.shared_params.response_format_json_schema import (
	JSONSchema,
	ResponseFormatJSONSchema,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, ContentPartTextParam, SystemMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.vercel.serializer import VercelMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)

ChatVercelModel: TypeAlias = Literal[
	'alibaba/qwen-3-14b',
	'alibaba/qwen-3-235b',
	'alibaba/qwen-3-30b',
	'alibaba/qwen-3-32b',
	'alibaba/qwen3-coder',
	'alibaba/qwen3-coder-30b-a3b',
	'alibaba/qwen3-coder-plus',
	'alibaba/qwen3-max',
	'alibaba/qwen3-max-preview',
	'alibaba/qwen3-next-80b-a3b-instruct',
	'alibaba/qwen3-next-80b-a3b-thinking',
	'alibaba/qwen3-vl-instruct',
	'alibaba/qwen3-vl-thinking',
	'amazon/nova-lite',
	'amazon/nova-micro',
	'amazon/nova-pro',
	'amazon/titan-embed-text-v2',
	'anthropic/claude-3-haiku',
	'anthropic/claude-3-opus',
	'anthropic/claude-3.5-haiku',
	'anthropic/claude-3.5-sonnet',
	'anthropic/claude-3.5-sonnet-20240620',
	'anthropic/claude-3.7-sonnet',
	'anthropic/claude-haiku-4.5',
	'anthropic/claude-opus-4',
	'anthropic/claude-opus-4.1',
	'anthropic/claude-sonnet-4',
	'anthropic/claude-sonnet-4.5',
	'cohere/command-a',
	'cohere/command-r',
	'cohere/command-r-plus',
	'cohere/embed-v4.0',
	'deepseek/deepseek-r1',
	'deepseek/deepseek-r1-distill-llama-70b',
	'deepseek/deepseek-v3',
	'deepseek/deepseek-v3.1',
	'deepseek/deepseek-v3.1-base',
	'deepseek/deepseek-v3.1-terminus',
	'deepseek/deepseek-v3.2-exp',
	'deepseek/deepseek-v3.2-exp-thinking',
	'google/gemini-2.0-flash',
	'google/gemini-2.0-flash-lite',
	'google/gemini-2.5-flash',
	'google/gemini-2.5-flash-image',
	'google/gemini-2.5-flash-image-preview',
	'google/gemini-2.5-flash-lite',
	'google/gemini-2.5-flash-lite-preview-09-2025',
	'google/gemini-2.5-flash-preview-09-2025',
	'google/gemini-2.5-pro',
	'google/gemini-embedding-001',
	'google/gemma-2-9b',
	'google/text-embedding-005',
	'google/text-multilingual-embedding-002',
	'inception/mercury-coder-small',
	'meituan/longcat-flash-chat',
	'meituan/longcat-flash-thinking',
	'meta/llama-3-70b',
	'meta/llama-3-8b',
	'meta/llama-3.1-70b',
	'meta/llama-3.1-8b',
	'meta/llama-3.2-11b',
	'meta/llama-3.2-1b',
	'meta/llama-3.2-3b',
	'meta/llama-3.2-90b',
	'meta/llama-3.3-70b',
	'meta/llama-4-maverick',
	'meta/llama-4-scout',
	'mistral/codestral',
	'mistral/codestral-embed',
	'mistral/devstral-small',
	'mistral/magistral-medium',
	'mistral/magistral-medium-2506',
	'mistral/magistral-small',
	'mistral/magistral-small-2506',
	'mistral/ministral-3b',
	'mistral/ministral-8b',
	'mistral/mistral-embed',
	'mistral/mistral-large',
	'mistral/mistral-medium',
	'mistral/mistral-small',
	'mistral/mixtral-8x22b-instruct',
	'mistral/pixtral-12b',
	'mistral/pixtral-large',
	'moonshotai/kimi-k2',
	'moonshotai/kimi-k2-0905',
	'moonshotai/kimi-k2-turbo',
	'morph/morph-v3-fast',
	'morph/morph-v3-large',
	'openai/gpt-3.5-turbo',
	'openai/gpt-3.5-turbo-instruct',
	'openai/gpt-4-turbo',
	'openai/gpt-4.1',
	'openai/gpt-4.1-mini',
	'openai/gpt-4.1-nano',
	'openai/gpt-4o',
	'openai/gpt-4o-mini',
	'openai/gpt-5',
	'openai/gpt-5-codex',
	'openai/gpt-5-mini',
	'openai/gpt-5-nano',
	'openai/gpt-5-pro',
	'openai/gpt-oss-120b',
	'openai/gpt-oss-20b',
	'openai/o1',
	'openai/o3',
	'openai/o3-mini',
	'openai/o4-mini',
	'openai/text-embedding-3-large',
	'openai/text-embedding-3-small',
	'openai/text-embedding-ada-002',
	'perplexity/sonar',
	'perplexity/sonar-pro',
	'perplexity/sonar-reasoning',
	'perplexity/sonar-reasoning-pro',
	'stealth/sonoma-dusk-alpha',
	'stealth/sonoma-sky-alpha',
	'vercel/v0-1.0-md',
	'vercel/v0-1.5-md',
	'voyage/voyage-3-large',
	'voyage/voyage-3.5',
	'voyage/voyage-3.5-lite',
	'voyage/voyage-code-2',
	'voyage/voyage-code-3',
	'voyage/voyage-finance-2',
	'voyage/voyage-law-2',
	'xai/grok-2',
	'xai/grok-2-vision',
	'xai/grok-3',
	'xai/grok-3-fast',
	'xai/grok-3-mini',
	'xai/grok-3-mini-fast',
	'xai/grok-4',
	'xai/grok-4-fast-non-reasoning',
	'xai/grok-4-fast-reasoning',
	'xai/grok-code-fast-1',
	'zai/glm-4.5',
	'zai/glm-4.5-air',
	'zai/glm-4.5v',
	'zai/glm-4.6',
]


@dataclass
class ChatVercel(BaseChatModel):
	"""
	A wrapper around Vercel AI Gateway's API, which provides OpenAI-compatible access
	to various LLM models with features like rate limiting, caching, and monitoring.

	Examples:
		```python
	        from browser_use import Agent, ChatVercel

	        llm = ChatVercel(model='openai/gpt-4o', api_key='your_vercel_api_key')

	        agent = Agent(task='Your task here', llm=llm)
		```

	Args:
	    model: The model identifier
	    api_key: Your Vercel API key
	    base_url: The Vercel AI Gateway endpoint (defaults to https://ai-gateway.vercel.sh/v1)
	    temperature: Sampling temperature (0-2)
	    max_tokens: Maximum tokens to generate
	    reasoning_models: List of reasoning model patterns (e.g., 'o1', 'gpt-oss') that need
	        prompt-based JSON extraction. Auto-detects common reasoning models by default.
	    timeout: Request timeout in seconds
	    max_retries: Maximum number of retries for failed requests
	"""

	# Model configuration
	model: ChatVercelModel | str

	# Model params
	temperature: float | None = None
	max_tokens: int | None = None
	top_p: float | None = None
	reasoning_models: list[str] | None = field(
		default_factory=lambda: [
			'o1',
			'o3',
			'o4',
			'gpt-oss',
			'deepseek-r1',
			'qwen3-next-80b-a3b-thinking',
		]
	)

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = 'https://ai-gateway.vercel.sh/v1'
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 5
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None
	_strict_response_validation: bool = False

	# Static
	@property
	def provider(self) -> str:
		return 'vercel'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		base_params = {
			'api_key': self.api_key,
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': self.default_headers,
			'default_query': self.default_query,
			'_strict_response_validation': self._strict_response_validation,
		}

		client_params = {k: v for k, v in base_params.items() if v is not None}

		if self.http_client is not None:
			client_params['http_client'] = self.http_client

		return client_params

	def get_client(self) -> AsyncOpenAI:
		"""
		Returns an AsyncOpenAI client configured for Vercel AI Gateway.

		Returns:
		    AsyncOpenAI: An instance of the AsyncOpenAI client with Vercel base URL.
		"""
		if not hasattr(self, '_client'):
			client_params = self._get_client_params()
			self._client = AsyncOpenAI(**client_params)
		return self._client

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		"""Extract usage information from the Vercel response."""
		if response.usage is None:
			return None

		prompt_details = getattr(response.usage, 'prompt_tokens_details', None)
		cached_tokens = prompt_details.cached_tokens if prompt_details else None

		return ChatInvokeUsage(
			prompt_tokens=response.usage.prompt_tokens,
			prompt_cached_tokens=cached_tokens,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=response.usage.completion_tokens,
			total_tokens=response.usage.total_tokens,
		)

	def _fix_gemini_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
		"""
		Convert a Pydantic model to a Gemini-compatible schema.

		This function removes unsupported properties like 'additionalProperties' and resolves
		$ref references that Gemini doesn't support.
		"""

		# Handle $defs and $ref resolution
		if '$defs' in schema:
			defs = schema.pop('$defs')

			def resolve_refs(obj: Any) -> Any:
				if isinstance(obj, dict):
					if '$ref' in obj:
						ref = obj.pop('$ref')
						ref_name = ref.split('/')[-1]
						if ref_name in defs:
							# Replace the reference with the actual definition
							resolved = defs[ref_name].copy()
							# Merge any additional properties from the reference
							for key, value in obj.items():
								if key != '$ref':
									resolved[key] = value
							return resolve_refs(resolved)
						return obj
					else:
						# Recursively process all dictionary values
						return {k: resolve_refs(v) for k, v in obj.items()}
				elif isinstance(obj, list):
					return [resolve_refs(item) for item in obj]
				return obj

			schema = resolve_refs(schema)

		# Remove unsupported properties
		def clean_schema(obj: Any) -> Any:
			if isinstance(obj, dict):
				# Remove unsupported properties
				cleaned = {}
				for key, value in obj.items():
					if key not in ['additionalProperties', 'title', 'default']:
						cleaned_value = clean_schema(value)
						# Handle empty object properties - Gemini doesn't allow empty OBJECT types
						if (
							key == 'properties'
							and isinstance(cleaned_value, dict)
							and len(cleaned_value) == 0
							and isinstance(obj.get('type', ''), str)
							and obj.get('type', '').upper() == 'OBJECT'
						):
							# Convert empty object to have at least one property
							cleaned['properties'] = {'_placeholder': {'type': 'string'}}
						else:
							cleaned[key] = cleaned_value

				# If this is an object type with empty properties, add a placeholder
				if (
					isinstance(cleaned.get('type', ''), str)
					and cleaned.get('type', '').upper() == 'OBJECT'
					and 'properties' in cleaned
					and isinstance(cleaned['properties'], dict)
					and len(cleaned['properties']) == 0
				):
					cleaned['properties'] = {'_placeholder': {'type': 'string'}}

				# Also remove 'title' from the required list if it exists
				if 'required' in cleaned and isinstance(cleaned.get('required'), list):
					cleaned['required'] = [p for p in cleaned['required'] if p != 'title']

				return cleaned
			elif isinstance(obj, list):
				return [clean_schema(item) for item in obj]
			return obj

		return clean_schema(schema)

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages through Vercel AI Gateway.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		vercel_messages = VercelMessageSerializer.serialize_messages(messages)

		try:
			model_params: dict[str, Any] = {}
			if self.temperature is not None:
				model_params['temperature'] = self.temperature
			if self.max_tokens is not None:
				model_params['max_tokens'] = self.max_tokens
			if self.top_p is not None:
				model_params['top_p'] = self.top_p

			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=vercel_messages,
					**model_params,
				)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
					stop_reason=response.choices[0].finish_reason if response.choices else None,
				)

			else:
				is_google_model = self.model.startswith('google/')
				is_reasoning_model = self.reasoning_models and any(
					str(pattern).lower() in str(self.model).lower() for pattern in self.reasoning_models
				)

				if is_google_model or is_reasoning_model:
					modified_messages = [m.model_copy(deep=True) for m in messages]

					schema = SchemaOptimizer.create_gemini_optimized_schema(output_format)
					json_instruction = f'\n\nIMPORTANT: You must respond with ONLY a valid JSON object (no markdown, no code blocks, no explanations) that exactly matches this schema:\n{json.dumps(schema, indent=2)}'

					instruction_added = False
					if modified_messages and modified_messages[0].role == 'system':
						if isinstance(modified_messages[0].content, str):
							modified_messages[0].content += json_instruction
							instruction_added = True
						elif isinstance(modified_messages[0].content, list):
							modified_messages[0].content.append(ContentPartTextParam(text=json_instruction))
							instruction_added = True
					elif modified_messages and modified_messages[-1].role == 'user':
						if isinstance(modified_messages[-1].content, str):
							modified_messages[-1].content += json_instruction
							instruction_added = True
						elif isinstance(modified_messages[-1].content, list):
							modified_messages[-1].content.append(ContentPartTextParam(text=json_instruction))
							instruction_added = True

					if not instruction_added:
						modified_messages.insert(0, SystemMessage(content=json_instruction))

					vercel_messages = VercelMessageSerializer.serialize_messages(modified_messages)

					response = await self.get_client().chat.completions.create(
						model=self.model,
						messages=vercel_messages,
						**model_params,
					)

					content = response.choices[0].message.content if response.choices else None

					if not content:
						raise ModelProviderError(
							message='No response from model',
							status_code=500,
							model=self.name,
						)

					try:
						text = content.strip()
						if text.startswith('```json') and text.endswith('```'):
							text = text[7:-3].strip()
						elif text.startswith('```') and text.endswith('```'):
							text = text[3:-3].strip()

						parsed_data = json.loads(text)
						parsed = output_format.model_validate(parsed_data)

						usage = self._get_usage(response)
						return ChatInvokeCompletion(
							completion=parsed,
							usage=usage,
							stop_reason=response.choices[0].finish_reason if response.choices else None,
						)

					except (json.JSONDecodeError, ValueError) as e:
						raise ModelProviderError(
							message=f'Failed to parse JSON response: {str(e)}. Raw response: {content[:200]}',
							status_code=500,
							model=self.name,
						) from e

				else:
					schema = SchemaOptimizer.create_optimized_json_schema(output_format)

					response_format_schema: JSONSchema = {
						'name': 'agent_output',
						'strict': True,
						'schema': schema,
					}

					response = await self.get_client().chat.completions.create(
						model=self.model,
						messages=vercel_messages,
						response_format=ResponseFormatJSONSchema(
							json_schema=response_format_schema,
							type='json_schema',
						),
						**model_params,
					)

					content = response.choices[0].message.content if response.choices else None

					if not content:
						raise ModelProviderError(
							message='Failed to parse structured output from model response - empty or null content',
							status_code=500,
							model=self.name,
						)

					usage = self._get_usage(response)
					parsed = output_format.model_validate_json(content)

					return ChatInvokeCompletion(
						completion=parsed,
						usage=usage,
						stop_reason=response.choices[0].finish_reason if response.choices else None,
					)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
