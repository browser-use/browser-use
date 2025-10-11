import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, overload

from google import genai
from google.auth.credentials import Credentials
from google.genai import types
from google.genai.types import Content, ContentListUnion, MediaModality, Part
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


VerifiedGeminiModels = Literal[
	'gemini-2.5-computer-use-preview-10-2025',
]


@dataclass
class ChatGeminiComputerUse(BaseChatModel):
	"""
	A wrapper for using Gemini Computer Use models with Browser Use.

	This integration leverages the Computer Use model's vision capabilities while using
	Browser Use's element-based action system. Computer Use tools are temporarily disabled
	for structured output requests to avoid conflicts between Computer Use's coordinate-based
	actions and Browser Use's element-based actions.

	Args:
		model: The Gemini model to use (default: gemini-2.5-computer-use-preview-10-2025)
		temperature: Temperature for response generation
		config: Additional configuration parameters to pass to generate_content
		api_key: Google API key
		vertexai: Whether to use Vertex AI
		credentials: Google credentials object
		project: Google Cloud project ID
		location: Google Cloud location
		http_options: HTTP options for the client
		include_system_in_user: If True, system messages are included in the first user message
		supports_structured_output: Use native JSON mode (automatically disabled if enable_computer_use=True)
		enable_computer_use: If True, enable Gemini Computer Use tools for vision (disabled for structured output)
		excluded_predefined_functions: Optional list of UI action names to exclude

	Example (Browser Use integration with Computer Use):
		llm = ChatGeminiComputerUse(
			model='gemini-2.5-computer-use-preview-10-2025',
			api_key='your-api-key',
			enable_computer_use=True
		)
		agent = Agent(task='Go to news.ycombinator.com and get the top article', llm=llm)
		# The integration automatically:
		# 1. Uses Computer Use model for enhanced vision capabilities
		# 2. Enables Computer Use tools for text responses (vision processing)
		# 3. Disables Computer Use tools for structured output (to avoid action conflicts)
		# 4. Returns Browser Use actions (element-based: click index 123, not click x/y)
	"""

	# Model configuration
	model: VerifiedGeminiModels
	temperature: float | None = 0.2  # Currently not configurable as of 10/08/2025
	top_p: float | None = None
	seed: int | None = None
	thinking_budget: int | None = None
	max_output_tokens: int | None = 8192  # Computer Use supports up to 64K output tokens
	config: types.GenerateContentConfigDict | None = None
	include_system_in_user: bool = True  # Default to True for Computer Use
	supports_structured_output: bool = False  # Computer Use doesn't support JSON mode with function calling
	enable_computer_use: bool = True  # Automatically configure computer use tools
	excluded_predefined_functions: list[str] | None = None  # Optional: block specific UI actions

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
		return 'google_computer_use'

	@property
	def logger(self) -> logging.Logger:
		"""Get logger for this chat instance"""
		return logging.getLogger(f'browser_use.llm.gemini_computer_use.{self.model}')

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

	def _configure_computer_use(self, config: types.GenerateContentConfigDict) -> types.GenerateContentConfigDict:
		"""
		Configure computer use tools if enabled and not already configured.

		Args:
			config: The existing config dictionary

		Returns:
			Updated config with computer use tools if needed
		"""
		if not self.enable_computer_use:
			self.logger.debug('🔧 Computer Use disabled, using Browser Use actions with vision support')
			return config

		# Computer Use enabled - force structured output off (incompatible with function calling)
		if self.supports_structured_output:
			self.logger.warning(
				'⚠️ Computer Use does not support structured output (JSON mode). '
				'Forcing supports_structured_output=False.'
			)
			self.supports_structured_output = False

		# Check if tools are already configured
		if 'tools' in config:
			self.logger.debug('🔧 Tools already configured in config')
			return config

		# Build Computer Use configuration
		self.logger.debug('🖥️ Configuring Computer Use tools for vision capabilities')
		computer_use_config = types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER)

		# Add user-specified excluded functions if any
		if self.excluded_predefined_functions:
			self.logger.debug(f'🚫 Excluding {len(self.excluded_predefined_functions)} user-specified UI actions')
			computer_use_config.excluded_predefined_functions = self.excluded_predefined_functions

		config['tools'] = [  # type: ignore
			types.Tool(computer_use=computer_use_config)
		]

		return config

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

		# Serialize messages to Google format with Computer Use optimizations
		contents, system_instruction = GeminiComputerUseMessageSerializer.serialize_messages(
			messages, include_system_in_user=self.include_system_in_user
		)

		# Build config dictionary starting with user-provided config
		config: types.GenerateContentConfigDict = {}
		if self.config:
			config = self.config.copy()

		# Configure computer use tools if enabled
		# NOTE: Computer Use Model REQUIRES Computer Use tool - cannot be disabled
		# We handle function calls gracefully in fallback mode by asking for text summary
		config = self._configure_computer_use(config)

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
					# Return string response OR raw response with function calls
					self.logger.debug('📄 Requesting text response')

					response = await self.get_client().aio.models.generate_content(
						model=self.model,
						contents=contents,  # type: ignore
						config=config,
					)

					elapsed = time.time() - start_time
					self.logger.debug(f'✅ Got text response in {elapsed:.2f}s')

					usage = self._get_usage(response)

					# If Computer Use is enabled, return raw response for function call handling
					# This allows ComputerUseAgent to access function calls
					if self.enable_computer_use:
						# Check if we have function calls
						has_function_calls = False
						if response.candidates and len(response.candidates) > 0:
							candidate = response.candidates[0]
							if candidate.content and candidate.content.parts:
								has_function_calls = any(
									hasattr(part, 'function_call') and part.function_call
									for part in candidate.content.parts
								)

						if has_function_calls:
							self.logger.debug('🖱️  Response contains Computer Use function calls')
							# Return raw response so ComputerUseAgent can handle function calls
							return ChatInvokeCompletion(
								completion=response,  # type: ignore[arg-type] # Return raw response for Computer Use
								usage=usage,
							)

					# No function calls or Computer Use disabled - return text
					text = response.text or ''
					if not text:
						self.logger.warning('⚠️ Empty text response received')

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
						optimized_schema = SchemaOptimizer.create_gemini_optimized_schema(output_format)

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
							json_instruction = (
								f'\n\nIMPORTANT: Respond with a valid JSON object (as TEXT, not a function call) '
								f'that matches this schema: {SchemaOptimizer.create_optimized_json_schema(output_format)}\n'
								f'Do NOT use Computer Use UI actions (click_at, type_text_at, etc.). '
								f'Return JSON text describing the action to take using element indices.'
							)
							modified_messages[-1].content += json_instruction

						# Re-serialize with modified messages
						fallback_contents, fallback_system = GeminiComputerUseMessageSerializer.serialize_messages(
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

						# Try to extract JSON from the text response OR function calls
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
							# No text - check if we got function calls from Computer Use
							# Computer Use returns function calls for UI actions, but Browser Use handles actions differently
							# So we log this and ask the model to continue
							has_function_calls = False
							if (
								response.candidates
								and len(response.candidates) > 0
								and response.candidates[0].content is not None
								and response.candidates[0].content.parts is not None
							):
								has_function_calls = any(
									hasattr(part, 'function_call') and part.function_call
									for part in response.candidates[0].content.parts
								)

							if has_function_calls:
								# Computer Use returned function calls instead of JSON
								# This means it wants to take actions, but Browser Use can't use these
								# Return a "pending" response asking it to report what it would do
								self.logger.warning('⚠️ Computer Use returned function calls - Browser Use cannot execute these')
								self.logger.warning('Asking model to describe its intended actions as JSON instead')

								# Return empty action to trigger Browser Use to ask for text instead
								raise ModelProviderError(
									message=(
										'Computer Use returned function calls. Browser Use needs JSON text responses. '
										'The model should describe its actions in JSON format matching the schema instead of using function calls.'
									),
									status_code=500,
									model=self.model,
								)
							else:
								self.logger.error('❌ No response text or function calls')
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
			return await _make_api_call()  # type: ignore[return-value]

		except Exception as e:
			# Handle specific Google API errors with enhanced diagnostics
			error_message = str(e)
			status_code: int | None = None

			# Enhanced timeout error handling
			if 'timeout' in error_message.lower() or 'cancelled' in error_message.lower():
				if isinstance(e, asyncio.CancelledError) or 'CancelledError' in str(type(e)):
					enhanced_message = 'Gemini Computer Use API request was cancelled (likely timeout). '
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


class GeminiComputerUseMessageSerializer:
	"""Serializer for converting messages to Gemini Computer Use format."""

	@staticmethod
	def serialize_messages(
		messages: list[BaseMessage], include_system_in_user: bool = True
	) -> tuple[ContentListUnion, str | None]:
		"""
		Convert a list of BaseMessages to Gemini Computer Use format.

		Args:
			messages: List of messages to convert
			include_system_in_user: If True, system/developer messages are prepended to the first user message

		Returns:
			A tuple of (formatted_messages, system_message) where:
			- formatted_messages: List of Content objects for the conversation
			- system_message: System instruction string or None
		"""

		messages = [m.model_copy(deep=True) for m in messages]

		formatted_messages: ContentListUnion = []
		system_message: str | None = None
		system_parts: list[str] = []

		for message in messages:
			# Check if this is already a Gemini Content object (from function responses)
			# If so, add it directly without conversion
			if isinstance(message, Content):
				formatted_messages.append(message)  # type: ignore
				continue

			role = message.role if hasattr(message, 'role') else None

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				# Extract system message content as string
				if isinstance(message.content, str):
					if include_system_in_user:
						system_parts.append(message.content)
					else:
						system_message = message.content
				elif message.content is not None:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if part.type == 'text':
							parts.append(part.text)
					combined_text = '\n'.join(parts)
					if include_system_in_user:
						system_parts.append(combined_text)
					else:
						system_message = combined_text
				continue

			# Determine the role for non-system messages
			if isinstance(message, UserMessage):
				role = 'user'
			elif isinstance(message, AssistantMessage):
				role = 'model'
			else:
				# Default to user for any unknown message types
				role = 'user'

			# Initialize message parts
			message_parts: list[Part] = []

			# If this is the first user message and we have system parts, prepend them
			if include_system_in_user and system_parts and role == 'user' and not formatted_messages:
				system_text = '\n\n'.join(system_parts)
				if isinstance(message.content, str):
					message_parts.append(Part.from_text(text=f'{system_text}\n\n{message.content}'))
				else:
					# Add system text as the first part
					message_parts.append(Part.from_text(text=system_text))
				system_parts = []  # Clear after using
			else:
				# Extract content and create parts normally
				if isinstance(message.content, str):
					# Regular text content
					message_parts = [Part.from_text(text=message.content)]
				elif message.content is not None:
					# Handle Iterable of content parts
					for part in message.content:
						if part.type == 'text':
							message_parts.append(Part.from_text(text=part.text))
						elif part.type == 'refusal':
							message_parts.append(Part.from_text(text=f'[Refusal] {part.refusal}'))
						elif part.type == 'image_url':
							# Handle images - crucial for Computer Use which relies on screenshots
							url = part.image_url.url

							# Format: data:image/jpeg;base64,<data>
							header, data = url.split(',', 1)
							# Decode base64 to bytes
							image_bytes = base64.b64decode(data)

							# Determine mime type from header
							mime_type = 'image/jpeg'  # default
							if 'image/png' in header:
								mime_type = 'image/png'
							elif 'image/webp' in header:
								mime_type = 'image/webp'

							# Add image part
							image_part = Part.from_bytes(data=image_bytes, mime_type=mime_type)

							message_parts.append(image_part)

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				# for some reason, the type checker is not able to infer the type of formatted_messages
				formatted_messages.append(final_message)  # type: ignore

		return formatted_messages, system_message

# Serializer class added from serializer.py
