import asyncio
import json
import logging
import time
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
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


VerifiedGeminiModels = Literal[
	'gemini-2.0-flash',
	'gemini-2.0-flash-exp',
	'gemini-2.0-flash-lite-preview-02-05',
	'Gemini-2.0-exp',
	'gemini-2.5-flash',
	'gemini-2.5-flash-lite',
	'gemini-2.5-pro',
	'gemma-3-27b-it',
	'gemma-3-4b',
	'gemma-3-12b',
	'gemma-3n-e2b',
	'gemma-3n-e4b',
]


@dataclass
class ChatGoogle(BaseChatModel):
	"""
	A wrapper around Google's Gemini chat model using the genai client.

	This class accepts all genai.Client parameters while adding model,
	temperature, and config parameters for the LLM interface.

	Args:
		model: The Gemini model to use
		temperature: Temperature for response generation
		config: Additional configuration parameters to pass to generate_content
			(e.g., tools, safety_settings, etc.).
		api_key: Google API key
		vertexai: Whether to use Vertex AI
		credentials: Google credentials object
		project: Google Cloud project ID
		location: Google Cloud location
		http_options: HTTP options for the client
		include_system_in_user: If True, system messages are included in the first user message
		supports_structured_output: If True, uses native JSON mode; if False, uses prompt-based fallback

	Example:
		from google.genai import types

		llm = ChatGoogle(
			model='gemini-2.0-flash-exp',
			config={
				'tools': [types.Tool(code_execution=types.ToolCodeExecution())]
			}
		)
	"""

	# Model configuration
	model: VerifiedGeminiModels | str
	temperature: float | None = 0.2
	top_p: float | None = None
	seed: int | None = None
	thinking_budget: int | None = None  # for gemini-2.5 flash and flash-lite models, default will be set to 0
	max_output_tokens: int | None = 8192
	config: types.GenerateContentConfigDict | None = None
	include_system_in_user: bool = False
	supports_structured_output: bool = True  # New flag

	# Client initialization parameters
	api_key: str | None = None
	vertexai: bool | None = None
	credentials: Credentials | None = None
	project: str | None = None
	location: str | None = None
	http_options: types.HttpOptions | types.HttpOptionsDict | None = None

	# Internal client cache to prevent connection issues
	_client: genai.Client | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'google'

	@property
	def logger(self) -> logging.Logger:
		"""Get logger for this chat instance"""
		return logging.getLogger(f'browser_use.llm.google.{self.model}')

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
		if self._client is not None:
			return self._client

		client_params = self._get_client_params()
		self._client = genai.Client(**client_params)
		return self._client

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
				completion_tokens=(response.usage_metadata.candidates_token_count or 0)
				+ (response.usage_metadata.thoughts_token_count or 0),
				total_tokens=response.usage_metadata.total_token_count or 0,
				prompt_cached_tokens=response.usage_metadata.cached_content_token_count,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=image_tokens,
			)

		return usage

	async def astream(self, messages: list[BaseMessage], output_format: type[T]):
		"""
		Streaming method that yields actions first, then full response for true parallel execution.
		"""
		contents, system_instruction = GoogleMessageSerializer.serialize_messages(
			messages, include_system_in_user=self.include_system_in_user
		)

		# Build config dictionary starting with user-provided config
		config: types.GenerateContentConfigDict = {}
		if self.config:
			config = self.config.copy()

		# Apply model-specific configuration
		if self.temperature is not None:
			config['temperature'] = self.temperature

		# Add system instruction if present
		if system_instruction:
			config['system_instruction'] = system_instruction

		if self.top_p is not None:
			config['top_p'] = self.top_p

		if self.seed is not None:
			config['seed'] = self.seed

		# Set default for flash models
		if self.thinking_budget is None and ('gemini-2.5-flash' in self.model or 'gemini-flash' in self.model):
			self.thinking_budget = 0

		if self.thinking_budget is not None:
			thinking_config_dict: types.ThinkingConfigDict = {'thinking_budget': self.thinking_budget}
			config['thinking_config'] = thinking_config_dict

		if self.max_output_tokens is not None:
			config['max_output_tokens'] = self.max_output_tokens

		# Handle structured output
		config['response_mime_type'] = 'application/json'
		optimized_schema = SchemaOptimizer.create_optimized_json_schema(output_format)
		gemini_schema = self._fix_gemini_schema(optimized_schema)
		config['response_schema'] = gemini_schema

		# Create streaming request
		stream = await self.get_client().aio.models.generate_content_stream(
			model=self.model,
			contents=contents,
			config=config,
		)

		# Track streaming state
		full_response_text = ""
		stripped_response = ""
		actions_yielded = False
		last_chunk = None

		async for chunk in stream:
			if chunk.text:
				full_response_text += chunk.text
				stripped_response += chunk.text.strip().replace("\n", "").replace(" ", "")

				# Yield actions as soon as we detect them
				if not actions_yielded and "],\"thinking\":" in stripped_response:
					end_index = stripped_response.index("\"thinking\":")
					actions_json = stripped_response[:end_index]
					actions_json = actions_json.replace("{\"action\":", "")

					try:
						# Parse and validate actions
						actions_data = json.loads("{\"action\":" + actions_json + "]}")
						actions_completion = output_format.model_validate(actions_data)

						yield ChatInvokeCompletion(
							completion=actions_completion,
							usage=ChatInvokeUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
						)
						actions_yielded = True
					except (json.JSONDecodeError, ValueError) as e:
						pass  # Continue if we can't parse actions yet

			last_chunk = chunk

		# Calculate final usage from last chunk
		usage = self._get_usage(last_chunk) if last_chunk else ChatInvokeUsage(
			prompt_tokens=0, completion_tokens=0, total_tokens=0
		)

		# Yield final complete response
		if full_response_text:
			try:
				text = full_response_text.strip()
				if text.startswith('```json') and text.endswith('```'):
					text = text[7:-3].strip()
				elif text.startswith('```') and text.endswith('```'):
					text = text[3:-3].strip()

				parsed_data = json.loads(text)
				completion = output_format.model_validate(parsed_data)

				yield ChatInvokeCompletion(
					completion=completion,
					usage=usage
				)
			except (json.JSONDecodeError, ValueError) as e:
				raise ModelProviderError(
					message=f'Failed to parse final response: {str(e)}',
					status_code=500,
					model=self.model,
				) from e

	async def astream_parallel_tasks(self, messages: list[BaseMessage], output_format: type[T]) -> tuple[asyncio.Task, asyncio.Task]:
		"""
		Create two parallel tasks: one for actions, one for complete response.
		Returns a tuple of (actions_task, complete_response_task).
		"""
		contents, system_instruction = GoogleMessageSerializer.serialize_messages(
			messages, include_system_in_user=self.include_system_in_user
		)

		# Build config dictionary starting with user-provided config
		config: types.GenerateContentConfigDict = {}
		if self.config:
			config = self.config.copy()

		# Apply model-specific configuration
		if self.temperature is not None:
			config['temperature'] = self.temperature

		# Add system instruction if present
		if system_instruction:
			config['system_instruction'] = system_instruction

		if self.top_p is not None:
			config['top_p'] = self.top_p

		if self.seed is not None:
			config['seed'] = self.seed

		# Set default for flash models
		if self.thinking_budget is None and ('gemini-2.5-flash' in self.model or 'gemini-flash' in self.model):
			self.thinking_budget = 0

		if self.thinking_budget is not None:
			thinking_config_dict: types.ThinkingConfigDict = {'thinking_budget': self.thinking_budget}
			config['thinking_config'] = thinking_config_dict

		if self.max_output_tokens is not None:
			config['max_output_tokens'] = self.max_output_tokens

		# Handle structured output
		config['response_mime_type'] = 'application/json'
		optimized_schema = SchemaOptimizer.create_optimized_json_schema(output_format)
		gemini_schema = self._fix_gemini_schema(optimized_schema)
		config['response_schema'] = gemini_schema

		# Shared state for coordination between tasks
		actions_completion = None
		complete_response_completion = None
		stream_done = asyncio.Event()

		async def _actions_task() -> ChatInvokeCompletion[T] | None:
			"""Task that extracts and returns actions as soon as they're available."""
			nonlocal actions_completion
			
			# Create streaming request
			stream = await self.get_client().aio.models.generate_content_stream(
				model=self.model,
				contents=contents,
				config=config,
			)

			stripped_response = ""
			
			async for chunk in stream:
				if chunk.text:
					stripped_response += chunk.text.strip().replace("\n", "").replace(" ", "")

					# Extract actions as soon as we detect them
					if "],\"thinking\":" in stripped_response:
						end_index = stripped_response.index("\"thinking\":")
						actions_json = stripped_response[:end_index]
						actions_json = actions_json.replace("{\"action\":", "")

						try:
							# Parse and validate actions
							actions_data = json.loads("{\"action\":" + actions_json + "]}")
							actions_completion = ChatInvokeCompletion(
								completion=output_format.model_validate(actions_data),
								usage=ChatInvokeUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
							)
							return actions_completion
						except (json.JSONDecodeError, ValueError) as e:
							pass  # Continue if we can't parse actions yet

			# If we get here, no actions were found
			return None

		async def _complete_response_task() -> ChatInvokeCompletion[T]:
			"""Task that waits for the complete response."""
			nonlocal complete_response_completion
			
			# Create streaming request
			stream = await self.get_client().aio.models.generate_content_stream(
				model=self.model,
				contents=contents,
				config=config,
			)

			full_response_text = ""
			last_chunk = None

			async for chunk in stream:
				if chunk.text:
					full_response_text += chunk.text
				last_chunk = chunk

			# Calculate final usage from last chunk
			usage = self._get_usage(last_chunk) if last_chunk else ChatInvokeUsage(
				prompt_tokens=0, completion_tokens=0, total_tokens=0
			)

			# Parse final complete response
			if full_response_text:
				try:
					text = full_response_text.strip()
					if text.startswith('```json') and text.endswith('```'):
						text = text[7:-3].strip()
					elif text.startswith('```') and text.endswith('```'):
						text = text[3:-3].strip()

					parsed_data = json.loads(text)
					complete_response_completion = ChatInvokeCompletion(
						completion=output_format.model_validate(parsed_data),
						usage=usage
					)
					return complete_response_completion
				except (json.JSONDecodeError, ValueError) as e:
					raise ModelProviderError(
						message=f'Failed to parse final response: {str(e)}',
						status_code=500,
						model=self.model,
					) from e
			else:
				raise ModelProviderError(
					message='No response received from model',
					status_code=500,
					model=self.model,
				)

		# Create and return both tasks
		actions_task = asyncio.create_task(_actions_task())
		complete_response_task = asyncio.create_task(_complete_response_task())
		
		return actions_task, complete_response_task

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

		# Serialize messages to Google format with the include_system_in_user flag
		contents, system_instruction = GoogleMessageSerializer.serialize_messages(
			messages, include_system_in_user=self.include_system_in_user
		)

		# Build config dictionary starting with user-provided config
		config: types.GenerateContentConfigDict = {}
		if self.config:
			config = self.config.copy()

		# Apply model-specific configuration (these can override config)
		if self.temperature is not None:
			config['temperature'] = self.temperature

		# Add system instruction if present
		if system_instruction:
			config['system_instruction'] = system_instruction

		if self.top_p is not None:
			config['top_p'] = self.top_p

		if self.seed is not None:
			config['seed'] = self.seed

		# set default for flash, flash-lite, gemini-flash-lite-latest, and gemini-flash-latest models
		if self.thinking_budget is None and ('gemini-2.5-flash' in self.model or 'gemini-flash' in self.model):
			self.thinking_budget = 0

		if self.thinking_budget is not None:
			thinking_config_dict: types.ThinkingConfigDict = {'thinking_budget': self.thinking_budget}
			config['thinking_config'] = thinking_config_dict

		if self.max_output_tokens is not None:
			config['max_output_tokens'] = self.max_output_tokens

		async def _make_api_call():
			start_time = time.time()
			self.logger.debug(f'🚀 Starting API call to {self.model}')

			try:
				if output_format is None:
					# Return string response
					self.logger.debug('📄 Requesting text response')

					response = await self.get_client().aio.models.generate_content(
						model=self.model,
						contents=contents,  # type: ignore
						config=config,
					)

					elapsed = time.time() - start_time
					self.logger.debug(f'✅ Got text response in {elapsed:.2f}s')

					# Handle case where response.text might be None
					text = response.text or ''
					if not text:
						self.logger.warning('⚠️ Empty text response received')

					usage = self._get_usage(response)

					return ChatInvokeCompletion(
						completion=text,
						usage=usage,
					)

				else:
					# Handle structured output
					if self.supports_structured_output:
						# Use native JSON mode
						self.logger.debug(f'🔧 Requesting structured output for {output_format.__name__}')
						config['response_mime_type'] = 'application/json'
						# Convert Pydantic model to Gemini-compatible schema
						optimized_schema = SchemaOptimizer.create_optimized_json_schema(output_format)

						gemini_schema = self._fix_gemini_schema(optimized_schema)
						config['response_schema'] = gemini_schema

						response = await self.get_client().aio.models.generate_content(
							model=self.model,
							contents=contents,
							config=config,
						)

						elapsed = time.time() - start_time
						self.logger.debug(f'✅ Got structured response in {elapsed:.2f}s')

						usage = self._get_usage(response)

						# Handle case where response.parsed might be None
						if response.parsed is None:
							self.logger.debug('📝 Parsing JSON from text response')
							# When using response_schema, Gemini returns JSON as text
							if response.text:
								try:
									# Handle JSON wrapped in markdown code blocks (common Gemini behavior)
									text = response.text.strip()
									if text.startswith('```json') and text.endswith('```'):
										text = text[7:-3].strip()
										self.logger.debug('🔧 Stripped ```json``` wrapper from response')
									elif text.startswith('```') and text.endswith('```'):
										text = text[3:-3].strip()
										self.logger.debug('🔧 Stripped ``` wrapper from response')

									# Parse the JSON text and validate with the Pydantic model
									parsed_data = json.loads(text)
									return ChatInvokeCompletion(
										completion=output_format.model_validate(parsed_data),
										usage=usage,
									)
								except (json.JSONDecodeError, ValueError) as e:
									self.logger.error(f'❌ Failed to parse JSON response: {str(e)}')
									self.logger.debug(f'Raw response text: {response.text[:200]}...')
									raise ModelProviderError(
										message=f'Failed to parse or validate response {response}: {str(e)}',
										status_code=500,
										model=self.model,
									) from e
							else:
								self.logger.error('❌ No response text received')
								raise ModelProviderError(
									message=f'No response from model {response}',
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
					else:
						# Fallback: Request JSON in the prompt for models without native JSON mode
						self.logger.debug(f'🔄 Using fallback JSON mode for {output_format.__name__}')
						# Create a copy of messages to modify
						modified_messages = [m.model_copy(deep=True) for m in messages]

						# Add JSON instruction to the last message
						if modified_messages and isinstance(modified_messages[-1].content, str):
							json_instruction = f'\n\nPlease respond with a valid JSON object that matches this schema: {SchemaOptimizer.create_optimized_json_schema(output_format)}'
							modified_messages[-1].content += json_instruction

						# Re-serialize with modified messages
						fallback_contents, fallback_system = GoogleMessageSerializer.serialize_messages(
							modified_messages, include_system_in_user=self.include_system_in_user
						)

						# Update config with fallback system instruction if present
						fallback_config = config.copy()
						if fallback_system:
							fallback_config['system_instruction'] = fallback_system

						response = await self.get_client().aio.models.generate_content(
							model=self.model,
							contents=fallback_contents,  # type: ignore
							config=fallback_config,
						)

						elapsed = time.time() - start_time
						self.logger.debug(f'✅ Got fallback response in {elapsed:.2f}s')

						usage = self._get_usage(response)

						# Try to extract JSON from the text response
						if response.text:
							try:
								# Try to find JSON in the response
								text = response.text.strip()

								# Common patterns: JSON wrapped in markdown code blocks
								if text.startswith('```json') and text.endswith('```'):
									text = text[7:-3].strip()
								elif text.startswith('```') and text.endswith('```'):
									text = text[3:-3].strip()

								# Parse and validate
								parsed_data = json.loads(text)
								return ChatInvokeCompletion(
									completion=output_format.model_validate(parsed_data),
									usage=usage,
								)
							except (json.JSONDecodeError, ValueError) as e:
								self.logger.error(f'❌ Failed to parse fallback JSON: {str(e)}')
								self.logger.debug(f'Raw response text: {response.text[:200]}...')
								raise ModelProviderError(
									message=f'Model does not support JSON mode and failed to parse JSON from text response: {str(e)}',
									status_code=500,
									model=self.model,
								) from e
						else:
							self.logger.error('❌ No response text in fallback mode')
							raise ModelProviderError(
								message='No response from model',
								status_code=500,
								model=self.model,
							)
			except Exception as e:
				elapsed = time.time() - start_time
				self.logger.error(f'💥 API call failed after {elapsed:.2f}s: {type(e).__name__}: {e}')
				# Re-raise the exception
				raise

		try:
			# Let Google client handle retries internally with proper connection management
			self.logger.debug(f'🔄 Making API call to {self.model} (using built-in retry)')
			return await _make_api_call()

		except Exception as e:
			# Handle specific Google API errors with enhanced diagnostics
			error_message = str(e)
			status_code: int | None = None

			# Enhanced timeout error handling
			if 'timeout' in error_message.lower() or 'cancelled' in error_message.lower():
				if isinstance(e, asyncio.CancelledError) or 'CancelledError' in str(type(e)):
					enhanced_message = 'Gemini API request was cancelled (likely timeout). '
					enhanced_message += 'This suggests the API is taking too long to respond. '
					enhanced_message += (
						'Consider: 1) Reducing input size, 2) Using a different model, 3) Checking network connectivity.'
					)
					error_message = enhanced_message
					status_code = 504  # Gateway timeout
					self.logger.error(f'🕐 Timeout diagnosis: Model: {self.model}')
				else:
					status_code = 408  # Request timeout
			# Check if this is a rate limit error
			elif any(
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
