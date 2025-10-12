"""
OCI Raw API chat model integration for browser-use.

This module provides direct integration with Oracle Cloud Infrastructure's
Generative AI service using raw API calls without Langchain dependencies.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import TypeVar, overload

import oci
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
	BaseChatRequest,
	ChatDetails,
	CohereChatRequest,
	GenericChatRequest,
	OnDemandServingMode,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

from .serializer import OCIRawMessageSerializer

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatOCIRaw(BaseChatModel):
	"""
	A direct OCI Raw API integration for browser-use that bypasses Langchain.

	This class provides a browser-use compatible interface for OCI GenAI models
	using direct API calls to Oracle Cloud Infrastructure.

	Args:
	    model_id: The OCI GenAI model OCID
	    service_endpoint: The OCI service endpoint URL
	    compartment_id: The OCI compartment OCID
	    provider: The model provider (e.g., "meta", "cohere", "xai")
	    temperature: Temperature for response generation (0.0-2.0) - supported by all providers
	    max_tokens: Maximum tokens in response - supported by all providers
	    frequency_penalty: Frequency penalty for response generation - supported by Meta and Cohere only
	    presence_penalty: Presence penalty for response generation - supported by Meta only
	    top_p: Top-p sampling parameter - supported by all providers
	    top_k: Top-k sampling parameter - supported by Cohere and xAI only
	    auth_type: Authentication type (e.g., "API_KEY")
	    auth_profile: Authentication profile name
	    timeout: Request timeout in seconds
	"""

	# Model configuration
	model_id: str
	service_endpoint: str
	compartment_id: str
	provider: str = 'meta'

	# Model parameters
	temperature: float | None = 1.0
	max_tokens: int | None = 600
	frequency_penalty: float | None = 0.0
	presence_penalty: float | None = 0.0
	top_p: float | None = 0.75
	top_k: int | None = 0  # Used by Cohere models

	# Authentication
	auth_type: str = 'API_KEY'
	auth_profile: str = 'DEFAULT'

	# Client configuration
	timeout: float = 60.0

	# Static properties
	@property
	def provider_name(self) -> str:
		return 'oci-raw'

	@property
	def name(self) -> str:
		# Return a shorter name for telemetry (max 100 chars)
		if len(self.model_id) > 90:
			# Extract the model name from the OCID
			parts = self.model_id.split('.')
			if len(parts) >= 4:
				return f'oci-{self.provider}-{parts[3]}'  # e.g., "oci-meta-us-chicago-1"
			else:
				return f'oci-{self.provider}-model'
		return self.model_id

	@property
	def model(self) -> str:
		return self.model_id

	@property
	def model_name(self) -> str:
		# Override for telemetry - return shorter name (max 100 chars)
		if len(self.model_id) > 90:
			# Extract the model name from the OCID
			parts = self.model_id.split('.')
			if len(parts) >= 4:
				return f'oci-{self.provider}-{parts[3]}'  # e.g., "oci-meta-us-chicago-1"
			else:
				return f'oci-{self.provider}-model'
		return self.model_id

	def _uses_cohere_format(self) -> bool:
		"""Check if the provider uses Cohere chat request format."""
		return self.provider.lower() == 'cohere'

	def _get_supported_parameters(self) -> dict[str, bool]:
		"""Get which parameters are supported by the current provider."""
		provider = self.provider.lower()
		if provider == 'meta':
			return {
				'temperature': True,
				'max_tokens': True,
				'frequency_penalty': True,
				'presence_penalty': True,
				'top_p': True,
				'top_k': False,
			}
		elif provider == 'cohere':
			return {
				'temperature': True,
				'max_tokens': True,
				'frequency_penalty': True,
				'presence_penalty': False,
				'top_p': True,
				'top_k': True,
			}
		elif provider == 'xai':
			return {
				'temperature': True,
				'max_tokens': True,
				'frequency_penalty': False,
				'presence_penalty': False,
				'top_p': True,
				'top_k': True,
			}
		else:
			# Default: assume all parameters are supported
			return {
				'temperature': True,
				'max_tokens': True,
				'frequency_penalty': True,
				'presence_penalty': True,
				'top_p': True,
				'top_k': True,
			}

	def _get_oci_client(self) -> GenerativeAiInferenceClient:
		"""Get the OCI GenerativeAiInferenceClient following your working example."""
		if not hasattr(self, '_client'):
			# Configure OCI client based on auth_type (following your working example)
			if self.auth_type == 'API_KEY':
				config = oci.config.from_file('~/.oci/config', self.auth_profile)
				self._client = GenerativeAiInferenceClient(
					config=config,
					service_endpoint=self.service_endpoint,
					retry_strategy=oci.retry.NoneRetryStrategy(),
					timeout=(10, 240),  # Following your working example
				)
			elif self.auth_type == 'INSTANCE_PRINCIPAL':
				config = {}
				signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
				self._client = GenerativeAiInferenceClient(
					config=config,
					signer=signer,
					service_endpoint=self.service_endpoint,
					retry_strategy=oci.retry.NoneRetryStrategy(),
					timeout=(10, 240),
				)
			elif self.auth_type == 'RESOURCE_PRINCIPAL':
				config = {}
				signer = oci.auth.signers.get_resource_principals_signer()
				self._client = GenerativeAiInferenceClient(
					config=config,
					signer=signer,
					service_endpoint=self.service_endpoint,
					retry_strategy=oci.retry.NoneRetryStrategy(),
					timeout=(10, 240),
				)
			else:
				# Fallback to API_KEY
				config = oci.config.from_file('~/.oci/config', self.auth_profile)
				self._client = GenerativeAiInferenceClient(
					config=config,
					service_endpoint=self.service_endpoint,
					retry_strategy=oci.retry.NoneRetryStrategy(),
					timeout=(10, 240),
				)

		return self._client

	def _extract_usage(self, response) -> ChatInvokeUsage | None:
		"""Extract usage information from OCI response."""
		try:
			# The response is the direct OCI response object, not a dict
			if hasattr(response, 'data') and hasattr(response.data, 'chat_response'):
				chat_response = response.data.chat_response
				if hasattr(chat_response, 'usage'):
					usage = chat_response.usage
					return ChatInvokeUsage(
						prompt_tokens=getattr(usage, 'prompt_tokens', 0),
						prompt_cached_tokens=None,
						prompt_cache_creation_tokens=None,
						prompt_image_tokens=None,
						completion_tokens=getattr(usage, 'completion_tokens', 0),
						total_tokens=getattr(usage, 'total_tokens', 0),
					)
			return None
		except Exception:
			return None

	def _extract_content(self, response) -> str:
		"""Extract text content from OCI response."""
		try:
			# The response is the direct OCI response object, not a dict
			if not hasattr(response, 'data'):
				raise ModelProviderError(message='Invalid response format: no data attribute', status_code=500, model=self.name)

			chat_response = response.data.chat_response

			# Handle different response types based on provider
			if hasattr(chat_response, 'text'):
				# Cohere response format - has direct text attribute
				return chat_response.text or ''
			elif hasattr(chat_response, 'choices') and chat_response.choices:
				# Generic response format - has choices array (Meta, xAI)
				choice = chat_response.choices[0]
				message = choice.message
				content_parts = message.content

				# Extract text from content parts
				text_parts = []
				for part in content_parts:
					if hasattr(part, 'text'):
						text_parts.append(part.text)

				return '\n'.join(text_parts) if text_parts else ''
			else:
				raise ModelProviderError(
					message=f'Unsupported response format: {type(chat_response).__name__}', status_code=500, model=self.name
				)

		except Exception as e:
			raise ModelProviderError(
				message=f'Failed to extract content from response: {str(e)}', status_code=500, model=self.name
			) from e

	async def _make_request(self, messages: list[BaseMessage]):
		"""Make async request to OCI API using proper OCI SDK models."""

		# Create chat request based on provider type
		if self._uses_cohere_format():
			# Cohere models use CohereChatRequest with single message string
			message_text = OCIRawMessageSerializer.serialize_messages_for_cohere(messages)

			chat_request = CohereChatRequest()
			chat_request.message = message_text
			chat_request.max_tokens = self.max_tokens
			chat_request.temperature = self.temperature
			chat_request.frequency_penalty = self.frequency_penalty
			chat_request.top_p = self.top_p
			chat_request.top_k = self.top_k
		else:
			# Meta, xAI and other models use GenericChatRequest with messages array
			oci_messages = OCIRawMessageSerializer.serialize_messages(messages)

			chat_request = GenericChatRequest()
			chat_request.api_format = BaseChatRequest.API_FORMAT_GENERIC
			chat_request.messages = oci_messages
			chat_request.max_tokens = self.max_tokens
			chat_request.temperature = self.temperature
			chat_request.top_p = self.top_p

			# Provider-specific parameters
			if self.provider.lower() == 'meta':
				# Meta models support frequency_penalty and presence_penalty
				chat_request.frequency_penalty = self.frequency_penalty
				chat_request.presence_penalty = self.presence_penalty
			elif self.provider.lower() == 'xai':
				# xAI models support top_k but not frequency_penalty or presence_penalty
				chat_request.top_k = self.top_k
			else:
				# Default: include all parameters for unknown providers
				chat_request.frequency_penalty = self.frequency_penalty
				chat_request.presence_penalty = self.presence_penalty

		# Create serving mode
		serving_mode = OnDemandServingMode(model_id=self.model_id)

		# Create chat details
		chat_details = ChatDetails()
		chat_details.serving_mode = serving_mode
		chat_details.chat_request = chat_request
		chat_details.compartment_id = self.compartment_id

		# Make the request in a thread to avoid blocking
		def _sync_request():
			try:
				client = self._get_oci_client()
				response = client.chat(chat_details)
				return response  # Return the raw response object
			except Exception as e:
				# Handle OCI-specific exceptions
				status_code = getattr(e, 'status', 500)
				if status_code == 429:
					raise ModelRateLimitError(message=f'Rate limit exceeded: {str(e)}', model=self.name) from e
				else:
					raise ModelProviderError(message=str(e), status_code=status_code, model=self.name) from e

		# Run in thread pool to make it async
		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(None, _sync_request)

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the OCI GenAI model with the given messages using raw API.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		try:
			if output_format is None:
				# Return string response
				response = await self._make_request(messages)
				content = self._extract_content(response)
				usage = self._extract_usage(response)

				return ChatInvokeCompletion(
					completion=content,
					usage=usage,
				)
			else:
				# For structured output, add JSON schema instructions
				optimized_schema = SchemaOptimizer.create_optimized_json_schema(output_format)

				# Add JSON schema instruction to messages
				system_instruction = f"""
You must respond with ONLY a valid JSON object that matches this exact schema:
{json.dumps(optimized_schema, indent=2)}

IMPORTANT: 
- Your response must be ONLY the JSON object, no additional text
- The JSON must be valid and parseable
- All required fields must be present
- No extra fields are allowed
- Use proper JSON syntax with double quotes
"""

				# Clone messages and add system instruction
				modified_messages = messages.copy()

				# Add or modify system message
				from browser_use.llm.messages import SystemMessage

				if modified_messages and hasattr(modified_messages[0], 'role') and modified_messages[0].role == 'system':
					# Modify existing system message
					existing_content = modified_messages[0].content
					if isinstance(existing_content, str):
						modified_messages[0].content = existing_content + '\n\n' + system_instruction
					else:
						# Handle list content
						modified_messages[0].content = str(existing_content) + '\n\n' + system_instruction
				else:
					# Insert new system message at the beginning
					modified_messages.insert(0, SystemMessage(content=system_instruction))

				response = await self._make_request(modified_messages)
				response_text = self._extract_content(response)

				# Clean and parse the JSON response
				try:
					# Clean the response text
					cleaned_text = response_text.strip()

					# Remove markdown code blocks if present
					if cleaned_text.startswith('```json'):
						cleaned_text = cleaned_text[7:]
					if cleaned_text.startswith('```'):
						cleaned_text = cleaned_text[3:]
					if cleaned_text.endswith('```'):
						cleaned_text = cleaned_text[:-3]

					cleaned_text = cleaned_text.strip()

					# Try to find JSON object in the response
					if not cleaned_text.startswith('{'):
						start_idx = cleaned_text.find('{')
						end_idx = cleaned_text.rfind('}')
						if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
							cleaned_text = cleaned_text[start_idx : end_idx + 1]

					# Parse the JSON
					parsed_data = json.loads(cleaned_text)
					parsed = output_format.model_validate(parsed_data)

					usage = self._extract_usage(response)
					return ChatInvokeCompletion(
						completion=parsed,
						usage=usage,
					)

				except (json.JSONDecodeError, ValueError) as e:
					raise ModelProviderError(
						message=f'Failed to parse structured output: {str(e)}. Response was: {response_text[:200]}...',
						status_code=500,
						model=self.name,
					) from e

		except ModelRateLimitError:
			# Re-raise rate limit errors as-is
			raise
		except ModelProviderError:
			# Re-raise provider errors as-is
			raise
		except Exception as e:
			# Handle any other exceptions
			raise ModelProviderError(
				message=f'Unexpected error: {str(e)}',
				status_code=500,
				model=self.name,
			) from e
