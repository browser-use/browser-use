from dataclasses import dataclass
from typing import Any, Dict, Type, TypeVar

from google import genai
from google.auth.credentials import Credentials
from google.genai import types
from pydantic import BaseModel

from browser_use.llm import BaseMessage
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.google.serializer import GoogleMessageSerializer

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatGoogle(BaseChatModel):
	"""
	A wrapper around Google's Gemini chat model using the genai client.

	This class accepts all genai.Client parameters while adding model_name
	and temperature parameters for the LLM interface.
	"""

	# Model configuration
	model_name: str
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

	def _get_client_params(self) -> Dict[str, Any]:
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
	def llm_type(self) -> str:
		return 'google'

	@property
	def name(self) -> str:
		return str(self.model_name)

	async def ainvoke(self, messages: list[BaseMessage], output_format: Type[T] | None = None) -> T | str:
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

		# For now, convert contents to a single string for simplicity
		# This matches the example usage pattern
		content_parts = []
		if system_instruction and system_instruction.parts:
			for part in system_instruction.parts:
				if part.text:
					content_parts.append(f'System: {part.text}')

		for content in contents:
			role_prefix = 'User' if content.role == 'user' else 'Assistant'
			if content.parts:
				for part in content.parts:
					if part.text:
						content_parts.append(f'{role_prefix}: {part.text}')

		contents_str = '\n\n'.join(content_parts)

		try:
			if output_format is None:
				# Return string response
				config: types.GenerateContentConfigDict = {}
				if self.temperature is not None:
					config['temperature'] = self.temperature

				response = await self.get_client().aio.models.generate_content(
					model=self.model_name,
					contents=contents_str,
					config=config if config else None,
				)

				# Handle case where response.text might be None
				if response.text is None:
					return ''
				return response.text

			else:
				# Return structured response
				config: types.GenerateContentConfigDict = {
					'response_mime_type': 'application/json',
					'response_schema': output_format,
				}
				if self.temperature is not None:
					config['temperature'] = self.temperature

				response = await self.get_client().aio.models.generate_content(
					model=self.model_name,
					contents=contents_str,
					config=config,
				)

				# The parsed response is already a Pydantic model instance
				if response.parsed is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model_name=self.name,
					)

				# Ensure we return the correct type
				if isinstance(response.parsed, output_format):
					return response.parsed
				else:
					# If it's not the expected type, try to validate it
					return output_format.model_validate(response.parsed)

		except Exception as e:
			# Handle specific Google API errors
			error_message = str(e)
			status_code: int | None = None

			# Try to extract status code if available
			if hasattr(e, 'response'):
				response_obj = getattr(e, 'response', None)
				if response_obj and hasattr(response_obj, 'status_code'):
					status_code = getattr(response_obj, 'status_code', None)

			raise ModelProviderError(
				message=error_message,
				status_code=status_code or 502,  # Use default if None
				model_name=self.name,
			) from e
