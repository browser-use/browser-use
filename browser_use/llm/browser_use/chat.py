"""
ChatBrowserUse - Client for browser-use cloud API

This wraps the BaseChatModel protocol and sends requests to the browser-use cloud API
for optimized browser automation LLM inference.
"""

import asyncio
import logging
import os
import random
from typing import Any, TypeVar, overload

import httpx
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.observability import observe

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)

# HTTP status codes that should trigger a retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ChatBrowserUse(BaseChatModel):
	"""
	Client for browser-use cloud API.

	This sends requests to the browser-use cloud API which uses optimized models
	and prompts for browser automation tasks.

	Usage:
		agent = Agent(
			task="Find the number of stars of the browser-use repo",
			llm=ChatBrowserUse(model='bu-latest'),
		)
	"""

	def __init__(
		self,
		model: str = 'bu-latest',
		api_key: str | None = None,
		base_url: str | None = None,
		timeout: float = 120.0,
		max_retries: int = 5,
		retry_base_delay: float = 1.0,
		retry_max_delay: float = 60.0,
		**kwargs,
	):
		"""
		Initialize ChatBrowserUse client.

		Args:
			model: Model name to use. Options:
				- 'bu-latest' or 'bu-1-0': Default model
				- 'browser-use/bu-30b-a3b-preview': Browser Use Open Source Model
			api_key: API key for browser-use cloud. Defaults to BROWSER_USE_API_KEY env var.
			base_url: Base URL for the API. Defaults to BROWSER_USE_LLM_URL env var or production URL.
			timeout: Request timeout in seconds.
			max_retries: Maximum number of retries for transient errors (default: 5).
			retry_base_delay: Base delay in seconds for exponential backoff (default: 1.0).
			retry_max_delay: Maximum delay in seconds between retries (default: 60.0).
		"""
		# Validate model name - allow bu-* and browser-use/* patterns
		valid_models = ['bu-latest', 'bu-1-0']
		is_valid = model in valid_models or model.startswith('browser-use/')
		if not is_valid:
			raise ValueError(f"Invalid model: '{model}'. Must be one of {valid_models} or start with 'browser-use/'")

		# Normalize bu-latest to bu-1-0 for default models
		if model == 'bu-latest':
			self.model = 'bu-1-0'
		else:
			self.model = model

		self.fast = False
		self.api_key = api_key or os.getenv('BROWSER_USE_API_KEY')
		self.base_url = base_url or os.getenv('BROWSER_USE_LLM_URL', 'https://llm.api.browser-use.com')
		self.timeout = timeout
		self.max_retries = max_retries
		self.retry_base_delay = retry_base_delay
		self.retry_max_delay = retry_max_delay

		if not self.api_key:
			raise ValueError(
				'You need to set the BROWSER_USE_API_KEY environment variable. '
				'Get your key at https://cloud.browser-use.com/new-api-key'
			)

	@property
	def provider(self) -> str:
		return 'browser-use'

	@property
	def name(self) -> str:
		return self.model

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, request_type: str = 'browser_agent', **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T], request_type: str = 'browser_agent', **kwargs: Any
	) -> ChatInvokeCompletion[T]: ...

	@observe(name='chat_browser_use_ainvoke')
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
		request_type: str = 'browser_agent',
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Send request to browser-use cloud API.

		Args:
			messages: List of messages to send
			output_format: Expected output format (Pydantic model)
			request_type: Type of request - 'browser_agent' or 'judge'
			**kwargs: Additional arguments, including:
				- session_id: Session ID for sticky routing (same session → same container)

		Returns:
			ChatInvokeCompletion with structured response and usage info
		"""
		# Get ANONYMIZED_TELEMETRY setting from config
		from browser_use.config import CONFIG

		anonymized_telemetry = CONFIG.ANONYMIZED_TELEMETRY

		# Extract session_id from kwargs for sticky routing
		session_id = kwargs.get('session_id')

		# Prepare request payload
		payload: dict[str, Any] = {
			'model': self.model,
			'messages': [self._serialize_message(msg) for msg in messages],
			'fast': self.fast,
			'request_type': request_type,
			'anonymized_telemetry': anonymized_telemetry,
		}

		# Add session_id for sticky routing if provided
		if session_id:
			payload['session_id'] = session_id

		# Add output format schema if provided
		if output_format is not None:
			payload['output_format'] = output_format.model_json_schema()

		last_error: Exception | None = None

		# Retry loop with exponential backoff
		for attempt in range(self.max_retries):
			try:
				result = await self._make_request(payload)
				break
			except httpx.HTTPStatusError as e:
				last_error = e
				status_code = e.response.status_code

				# Check if this is a retryable error
				if status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries - 1:
					delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
					jitter = random.uniform(0, delay * 0.1)
					total_delay = delay + jitter
					logger.warning(
						f'⚠️ Got {status_code} error, retrying in {total_delay:.1f}s... (attempt {attempt + 1}/{self.max_retries})'
					)
					await asyncio.sleep(total_delay)
					continue

				# Non-retryable HTTP error or exhausted retries
				self._raise_http_error(e)

			except (httpx.TimeoutException, httpx.ConnectError) as e:
				last_error = e
				# Network errors are retryable
				if attempt < self.max_retries - 1:
					delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
					jitter = random.uniform(0, delay * 0.1)
					total_delay = delay + jitter
					error_type = 'timeout' if isinstance(e, httpx.TimeoutException) else 'connection error'
					logger.warning(
						f'⚠️ Got {error_type}, retrying in {total_delay:.1f}s... (attempt {attempt + 1}/{self.max_retries})'
					)
					await asyncio.sleep(total_delay)
					continue

				# Exhausted retries
				if isinstance(e, httpx.TimeoutException):
					raise ValueError(f'Request timed out after {self.timeout}s (retried {self.max_retries} times)')
				raise ValueError(f'Failed to connect to browser-use API after {self.max_retries} attempts: {e}')

			except Exception as e:
				raise ValueError(f'Failed to connect to browser-use API: {e}')
		else:
			# Loop completed without break (all retries exhausted)
			if last_error is not None:
				if isinstance(last_error, httpx.HTTPStatusError):
					self._raise_http_error(last_error)
				raise ValueError(f'Request failed after {self.max_retries} attempts: {last_error}')
			raise RuntimeError('Retry loop completed without return or exception')

		# Parse response - server returns structured data as dict
		if output_format is not None:
			# Server returns structured data as a dict, validate it
			completion_data = result['completion']
			logger.debug(
				f'📥 Got structured data from service: {list(completion_data.keys()) if isinstance(completion_data, dict) else type(completion_data)}'
			)

			# Convert action dicts to ActionModel instances if needed
			# llm-use returns dicts to avoid validation with empty ActionModel
			if isinstance(completion_data, dict) and 'action' in completion_data:
				actions = completion_data['action']
				if actions and isinstance(actions[0], dict):
					from typing import get_args

					# Get ActionModel type from output_format
					action_model_type = get_args(output_format.model_fields['action'].annotation)[0]

					# Convert dicts to ActionModel instances
					completion_data['action'] = [action_model_type.model_validate(action_dict) for action_dict in actions]

			completion = output_format.model_validate(completion_data)
		else:
			completion = result['completion']

		# Parse usage info
		usage = None
		if 'usage' in result and result['usage'] is not None:
			from browser_use.llm.views import ChatInvokeUsage

			usage = ChatInvokeUsage(**result['usage'])

		return ChatInvokeCompletion(
			completion=completion,
			usage=usage,
		)

	async def _make_request(self, payload: dict) -> dict:
		"""Make a single API request."""
		async with httpx.AsyncClient(timeout=self.timeout) as client:
			response = await client.post(
				f'{self.base_url}/v1/chat/completions',
				json=payload,
				headers={
					'Authorization': f'Bearer {self.api_key}',
					'Content-Type': 'application/json',
				},
			)
			response.raise_for_status()
			return response.json()

	def _raise_http_error(self, e: httpx.HTTPStatusError) -> None:
		"""Raise appropriate ModelProviderError for HTTP errors."""
		error_detail = ''
		try:
			error_data = e.response.json()
			error_detail = error_data.get('detail', str(e))
		except Exception:
			error_detail = str(e)

		status_code = e.response.status_code

		if status_code == 401:
			raise ModelProviderError(message=f'Invalid API key. {error_detail}', status_code=401, model=self.name)
		elif status_code == 402:
			raise ModelProviderError(message=f'Insufficient credits. {error_detail}', status_code=402, model=self.name)
		elif status_code == 429:
			raise ModelRateLimitError(message=f'Rate limit exceeded. {error_detail}', status_code=429, model=self.name)
		elif status_code in {500, 502, 503, 504}:
			raise ModelProviderError(message=f'Server error. {error_detail}', status_code=status_code, model=self.name)
		else:
			raise ModelProviderError(message=f'API request failed: {error_detail}', status_code=status_code, model=self.name)

	def _serialize_message(self, message: BaseMessage) -> dict:
		"""Serialize a message to JSON format."""
		# Handle Union types by checking the actual message type
		msg_dict = message.model_dump()
		return {
			'role': msg_dict['role'],
			'content': msg_dict['content'],
		}
