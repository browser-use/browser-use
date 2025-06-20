import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Type, TypeVar, Union

import httpx
from anthropic import (
	APIConnectionError,
	APIStatusError,
	AsyncAnthropic,
	NotGiven,
	RateLimitError,
)
from anthropic.types import ToolParam
from anthropic.types.model_param import ModelParam
from anthropic.types.text_block import TextBlock
from anthropic.types.tool_choice_tool_param import ToolChoiceToolParam
from httpx import Timeout
from pydantic import BaseModel

from browser_use.llm import BaseMessage
from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAnthropic(BaseChatModel):
	"""
	A wrapper around Anthropic's chat model.
	"""

	# Model configuration
	model_name: str | ModelParam
	max_tokens: int
	temperature: float | None = None

	# Client initialization parameters
	api_key: str | None = None
	auth_token: str | None = None
	base_url: str | httpx.URL | None = None
	timeout: Union[float, Timeout, None, NotGiven] = NotGiven()
	max_retries: int = 2
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'anthropic'

	def _get_client_params(self) -> Dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Define base client params
		base_params = {
			'api_key': self.api_key,
			'auth_token': self.auth_token,
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': self.default_headers,
			'default_query': self.default_query,
		}

		# Create client_params dict with non-None values and non-NotGiven values
		client_params = {}
		for k, v in base_params.items():
			if v is not None and v is not NotGiven():
				client_params[k] = v

		return client_params

	def get_client(self) -> AsyncAnthropic:
		"""
		Returns an AsyncAnthropic client.

		Returns:
			AsyncAnthropic: An instance of the AsyncAnthropic client.
		"""
		client_params = self._get_client_params()
		return AsyncAnthropic(**client_params)

	@property
	def llm_type(self) -> str:
		return 'anthropic'

	@property
	def name(self) -> str:
		return str(self.model_name)

	async def ainvoke(self, messages: list[BaseMessage], output_format: Type[T] | None = None) -> T | str:
		anthropic_messages, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Normal completion without structured output
				response = await self.get_client().messages.create(
					max_tokens=self.max_tokens,
					model=self.model_name,
					messages=anthropic_messages,
					temperature=self.temperature or NotGiven(),
					system=system_prompt or NotGiven(),
				)

				# Extract text from the first content block
				first_content = response.content[0]
				if isinstance(first_content, TextBlock):
					return first_content.text
				else:
					# If it's not a text block, convert to string
					return str(first_content)
			else:
				# Use tool calling for structured output
				# Create a tool that represents the output format
				tool_name = output_format.__name__
				schema = output_format.model_json_schema()

				# Remove title from schema if present (Anthropic doesn't like it in parameters)
				if 'title' in schema:
					del schema['title']

				tool = ToolParam(
					name=tool_name, description=f'Extract information in the format of {tool_name}', input_schema=schema
				)

				# Force the model to use this tool
				tool_choice = ToolChoiceToolParam(type='tool', name=tool_name)

				response = await self.get_client().messages.create(
					max_tokens=self.max_tokens,
					model=self.model_name,
					messages=anthropic_messages,
					temperature=self.temperature or NotGiven(),
					system=system_prompt or NotGiven(),
					tools=[tool],
					tool_choice=tool_choice,
				)

				# Extract the tool use block
				for content_block in response.content:
					if hasattr(content_block, 'type') and content_block.type == 'tool_use':
						# Parse the tool input as the structured output
						try:
							return output_format.model_validate(content_block.input)
						except Exception as e:
							# If validation fails, try to parse it as JSON first
							if isinstance(content_block.input, str):
								data = json.loads(content_block.input)
								return output_format.model_validate(data)
							raise e

				# If no tool use block found, raise an error
				raise ValueError('Expected tool use in response but none found')

		except APIConnectionError as e:
			raise ModelProviderError(message=e.message, model_name=self.name) from e
		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model_name=self.name) from e
		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model_name=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model_name=self.name) from e
