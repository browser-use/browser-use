"""
ChatBrowserUse - Client for browser-use cloud API

This wraps the BaseChatModel protocol and sends requests to the browser-use cloud API
for optimized browser automation LLM inference.
"""

import logging
import os
from typing import TypeVar, overload

import httpx
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)


class ChatBrowserUse(BaseChatModel):
	"""
	Client for browser-use cloud API.

	This sends requests to the browser-use cloud API which uses optimized models
	and prompts for browser automation tasks.

	Usage:
		agent = Agent(
			task="Find the number of stars of the browser-use repo",
			llm=ChatBrowserUse(super_fast=True),
		)
	"""

	def __init__(
		self,
		super_fast: bool = True,
		api_key: str | None = None,
		base_url: str | None = None,
		timeout: float = 120.0,
	):
		"""
		Initialize ChatBrowserUse client.

		Args:
			super_fast: If True, uses fastest model. If False, uses balanced model.
			api_key: API key for browser-use cloud. Defaults to BROWSER_USE_API_KEY env var.
			base_url: Base URL for the API. Defaults to BROWSER_USE_API_URL env var or production URL.
			timeout: Request timeout in seconds.
		"""
		self.super_fast = super_fast
		self.api_key = api_key or os.getenv('BROWSER_USE_API_KEY', '12345678')
		self.base_url = base_url or os.getenv('BROWSER_USE_API_URL', 'https://api.browser-use.com')
		self.timeout = timeout
		self.model = 'gemini-flash-lite-latest' if super_fast else 'gemini-flash-latest'

	@property
	def provider(self) -> str:
		return 'browser-use'

	@property
	def name(self) -> str:
		return f'browser-use/{self.model}'

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Send request to browser-use cloud API.

		Args:
			messages: List of messages to send
			output_format: Expected output format (Pydantic model)

		Returns:
			ChatInvokeCompletion with structured response and usage info
		"""
		# Prepare request payload
		payload = {
			'messages': [self._serialize_message(msg) for msg in messages],
			'super_fast': self.super_fast,
		}

		# Add output format schema if provided
		if output_format is not None:
			payload['output_format'] = output_format.model_json_schema()

		# Make API request
		async with httpx.AsyncClient(timeout=self.timeout) as client:
			try:
				response = await client.post(
					f'{self.base_url}/v1/chat/completions',
					json=payload,
					headers={
						'Authorization': f'Bearer {self.api_key}',
						'Content-Type': 'application/json',
					},
				)
				response.raise_for_status()
				result = response.json()

			except httpx.HTTPStatusError as e:
				error_detail = ''
				try:
					error_data = e.response.json()
					error_detail = error_data.get('detail', str(e))
				except Exception:
					error_detail = str(e)

				if e.response.status_code == 401:
					raise ValueError(f'Invalid API key. {error_detail}')
				elif e.response.status_code == 402:
					raise ValueError(f'Insufficient credits. {error_detail}')
				else:
					raise ValueError(f'API request failed: {error_detail}')

			except httpx.TimeoutException:
				raise ValueError(f'Request timed out after {self.timeout}s')

			except Exception as e:
				raise ValueError(f'Failed to connect to browser-use API: {e}')

		# Parse response - server returns structured data as dict
		if output_format is not None:
			# Server returns structured output as a dict, validate it
			completion_data = result['completion']
			logger.debug(f'📥 Got structured data from service: {list(completion_data.keys()) if isinstance(completion_data, dict) else type(completion_data)}')
			completion = output_format.model_validate(completion_data)
		else:
			completion = result['completion']

		# Parse usage info
		usage = None
		if 'usage' in result:
			from browser_use.llm.views import ChatInvokeUsage

			usage = ChatInvokeUsage(**result['usage'])

		return ChatInvokeCompletion(
			completion=completion,
			usage=usage,
		)

	def _serialize_message(self, message: BaseMessage) -> dict:
		"""Serialize a message to JSON format."""
		# Handle Union types by checking the actual message type
		msg_dict = message.model_dump()
		return {
			'role': msg_dict['role'],
			'content': msg_dict['content'],
		}
