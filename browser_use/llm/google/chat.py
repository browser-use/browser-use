from dataclasses import dataclass
from typing import Any, Dict, Type, TypeVar, overload

from google import genai
from google.auth.credentials import Credentials
from google.genai import types
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import BaseMessage

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

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> str: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: Type[T]) -> T: ...

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

		# Return string response
		config: types.GenerateContentConfigDict = {}
		if self.temperature is not None:
			config['temperature'] = self.temperature

		# Add system instruction if present
		if system_instruction:
			config['system_instruction'] = system_instruction

		try:
			if output_format is None:
				# Return string response
				response = await self.get_client().aio.models.generate_content(
					model=self.model_name,
					contents=contents,  # type: ignore
					config=config,
				)

				# Handle case where response.text might be None
				if response.text is None:
					return ''
				return response.text

			else:
				# Return structured response
				config['response_mime_type'] = 'application/json'
				config['response_schema'] = output_format

				response = await self.get_client().aio.models.generate_content(
					model=self.model_name,
					contents=contents,  # type: ignore
					config=config,
				)

				# Handle case where response.parsed might be None
				if response.parsed is None:
					raise ModelProviderError(
						message='No parsed response from model',
						status_code=500,
						model_name=self.model_name,
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
