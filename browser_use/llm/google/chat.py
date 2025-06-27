import json
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, overload

from google import genai
from google.auth.credentials import Credentials
from google.genai import types
from google.genai.types import MediaModality
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


VerifiedGeminiModels = Literal[
	'gemini-2.0-flash', 'gemini-2.0-flash-exp', 'gemini-2.0-flash-lite-preview-02-05', 'Gemini-2.0-exp'
]


def _is_retryable_error(exception):
	"""Check if an error should be retried based on error message patterns."""
	error_msg = str(exception).lower()

	# Rate limit patterns
	rate_limit_patterns = ['rate limit', 'resource exhausted', 'quota exceeded', 'too many requests', '429']

	# Server error patterns
	server_error_patterns = ['service unavailable', 'internal server error', 'bad gateway', '503', '502', '500']

	# Connection error patterns
	connection_patterns = ['connection', 'timeout', 'network', 'unreachable']

	all_patterns = rate_limit_patterns + server_error_patterns + connection_patterns
	return any(pattern in error_msg for pattern in all_patterns)


@dataclass
class ChatGoogle(BaseChatModel):
	"""
	A wrapper around Google's Gemini chat model using the genai client.

	This class accepts all genai.Client parameters while adding model
	and temperature parameters for the LLM interface.
	"""

	# Model configuration
	model: VerifiedGeminiModels | str
	temperature: float | None = None

	# Client initialization parameters
	api_key: str | None = None
	vertexai: bool | None = None
	credentials: Credentials | None = None
	project: str | None = None
	location: str | None = None
	http_options: types.HttpOptions | types.HttpOptionsDict | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'google'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Define base client params
		base_params = {
			'api_key': self.api_key,
			'vertexai': self.vertexai,
			'credentials': self.credentials,
			'project': self.project,
			'location': self.location,
			'http_options': self.http_options,
		}

		# Create client_params dict with non-None values
		client_params = {k: v for k, v in base_params.items() if v is not None}

		return client_params

	def get_client(self) -> genai.Client:
		"""
		Returns a genai.Client instance.

		Returns:
			genai.Client: An instance of the Google genai client.
		"""
		client_params = self._get_client_params()
		return genai.Client(**client_params)

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: types.GenerateContentResponse) -> ChatInvokeUsage | None:
		usage: ChatInvokeUsage | None = None

		if response.usage_metadata is not None:
			image_tokens = 0
			if response.usage_metadata.prompt_tokens_details is not None:
				image_tokens = sum(
					detail.token_count or 0
					for detail in response.usage_metadata.prompt_tokens_details
					if detail.modality == MediaModality.IMAGE
				)

			usage = ChatInvokeUsage(
				prompt_tokens=response.usage_metadata.prompt_token_count or 0,
				completion_tokens=response.usage_metadata.candidates_token_count or 0,
				total_tokens=response.usage_metadata.total_token_count or 0,
				prompt_cached_tokens=response.usage_metadata.cached_content_token_count,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=image_tokens,
			)

		return usage

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""

		# Serialize messages to Google format
		contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages)

		# Return string response
		config: types.GenerateContentConfigDict = {}
		if self.temperature is not None:
			config['temperature'] = self.temperature

		# Add system instruction if present
		if system_instruction:
			config['system_instruction'] = system_instruction

		async def _make_api_call():
			if output_format is None:
				# Return string response
				response = await self.get_client().aio.models.generate_content(
					model=self.model,
					contents=contents,  # type: ignore
					config=config,
				)

				# Handle case where response.text might be None
				text = response.text or ''

				usage = self._get_usage(response)

				return ChatInvokeCompletion(
					completion=text,
					usage=usage,
				)

			else:
				# Return structured response
				config['response_mime_type'] = 'application/json'
				# Convert Pydantic model to Gemini-compatible schema
				config['response_schema'] = self._pydantic_to_gemini_schema(output_format)

				response = await self.get_client().aio.models.generate_content(
					model=self.model,
					contents=contents,
					config=config,
				)

				usage = self._get_usage(response)

				# Handle case where response.parsed might be None
				if response.parsed is None:
					# When using response_schema, Gemini returns JSON as text
					if response.text:
						try:
							# Parse the JSON text and validate with the Pydantic model
							parsed_data = json.loads(response.text)
							return ChatInvokeCompletion(
								completion=output_format.model_validate(parsed_data),
								usage=usage,
							)
						except (json.JSONDecodeError, ValueError) as e:
							raise ModelProviderError(
								message=f'Failed to parse or validate response: {str(e)}',
								status_code=500,
								model=self.model,
							) from e
					else:
						raise ModelProviderError(
							message='No response from model',
							status_code=500,
							model=self.model,
						)

				# Ensure we return the correct type
				if isinstance(response.parsed, output_format):
					return ChatInvokeCompletion(
						completion=response.parsed,
						usage=usage,
					)
				else:
					# If it's not the expected type, try to validate it
					return ChatInvokeCompletion(
						completion=output_format.model_validate(response.parsed),
						usage=usage,
					)

		try:
			# Use manual retry loop for Google API calls
			last_exception = None
			for attempt in range(10):  # Match our 10 retry attempts from other providers
				try:
					return await _make_api_call()
				except Exception as e:
					last_exception = e
					if not _is_retryable_error(e) or attempt == 9:  # Last attempt
						break

					# Simple exponential backoff
					import asyncio

					delay = min(60.0, 1.0 * (2.0**attempt))  # Cap at 60s
					await asyncio.sleep(delay)

			# Re-raise the last exception if all retries failed
			if last_exception:
				raise last_exception
			else:
				# This should never happen, but ensure we don't return None
				raise ModelProviderError(
					message='All retry attempts failed without exception',
					status_code=500,
					model=self.name,
				)

		except Exception as e:
			# Handle specific Google API errors
			error_message = str(e)
			status_code: int | None = None

			# Check if this is a rate limit error
			if any(
				indicator in error_message.lower()
				for indicator in ['rate limit', 'resource exhausted', 'quota exceeded', 'too many requests', '429']
			):
				status_code = 429
			elif any(
				indicator in error_message.lower()
				for indicator in ['service unavailable', 'internal server error', 'bad gateway', '503', '502', '500']
			):
				status_code = 503

			# Try to extract status code if available
			if hasattr(e, 'response'):
				response_obj = getattr(e, 'response', None)
				if response_obj and hasattr(response_obj, 'status_code'):
					status_code = getattr(response_obj, 'status_code', None)

			raise ModelProviderError(
				message=error_message,
				status_code=status_code or 502,  # Use default if None
				model=self.name,
			) from e

	def _pydantic_to_gemini_schema(self, model_class: type[BaseModel]) -> dict[str, Any]:
		"""
		Convert a Pydantic model to a Gemini-compatible schema.

		This function removes unsupported properties like 'additionalProperties' and resolves
		$ref references that Gemini doesn't support.
		"""
		schema = model_class.model_json_schema()

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
							and obj.get('type', '').upper() == 'OBJECT'
						):
							# Convert empty object to have at least one property
							cleaned['properties'] = {'_placeholder': {'type': 'string'}}
						else:
							cleaned[key] = cleaned_value

				# If this is an object type with empty properties, add a placeholder
				if (
					cleaned.get('type', '').upper() == 'OBJECT'
					and 'properties' in cleaned
					and isinstance(cleaned['properties'], dict)
					and len(cleaned['properties']) == 0
				):
					cleaned['properties'] = {'_placeholder': {'type': 'string'}}

				return cleaned
			elif isinstance(obj, list):
				return [clean_schema(item) for item in obj]
			return obj

		return clean_schema(schema)
