"""
ChatA3M - A3M Router chat model wrapper for browser-use.

Provides intelligent LLM routing for browser automation with:
- Automatic routing to cheapest capable model
- Stealth mode for anti-detection
- Parallel ensemble for reliability
- Parallel ensemble for reliable extraction

Requires the `a3m-router` package:
    pip install a3m-router

Usage:
    from browser_use import Agent
    from browser_use.llm.a3m import ChatA3M

    agent = Agent(
        task="Fill out this job application form",
        llm=ChatA3M(model="auto", stealth=True),
    )
"""

import logging
from dataclasses import dataclass
from typing import Any, overload

from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from pydantic import BaseModel

from browser_use.llm.a3m.serializer import A3MMessageSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage

logger = logging.getLogger(__name__)


class A3MRouterConfig(BaseModel):
	"""Configuration for A3M Router."""

	model: str = 'auto'
	stealth: bool = False
	parallel_ensemble: bool = False


@dataclass
class ChatA3M(BaseChatModel):
	"""A3M Router chat model for browser-use.

	A3M Router provides intelligent LLM routing with:
	- Automatic routing to cheapest capable model
	- 80+ supported providers
	- EXP3 game theory-based exploration/exploitation
	- MVT rate-limit rotation
	- ODT verification for adversarial patterns

	Args:
	    model: Model name or "auto" for automatic routing
	    stealth: Enable stealth mode for anti-detection
	    parallel_ensemble: Use parallel ensemble for reliability
	"""

	model: str = 'auto'
	stealth: bool = False
	parallel_ensemble: bool = False
	max_output_tokens: int = 8192
	type: str = 'chat_a3m'
	_a3m_router: Any = None

	def __post_init__(self) -> None:
		"""Initialize A3M router."""
		try:
			import a3m

			self._a3m_router = a3m.A3MRouter(  # type: ignore[attr-defined]
				model=self.model,
				stealth=self.stealth,
				parallel_ensemble=self.parallel_ensemble,
			)
			logger.info(f'Initialized A3M Router with model: {self.model}')
		except ImportError as e:
			raise ModelProviderError('A3M Router is not installed. Install with: pip install a3m-router') from e

	@property
	def provider(self) -> str:
		"""Return provider name."""
		return 'a3m-router'

	def messages_to_dict(self, messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""Convert browser-use messages to A3M Router format."""
		return A3MMessageSerializer.serialize(messages)

	@overload
	def generate(self, messages: list[BaseMessage]) -> str: ...

	@overload
	def generate(self, messages: list[BaseMessage], stream: bool) -> Any: ...

	def generate(self, messages: list[BaseMessage], stream: bool = False) -> Any:
		"""Generate response from A3M Router."""
		try:
			import a3m

			# Convert messages to A3M format
			a3m_messages = self.messages_to_dict(messages)

			# Use sync client for non-streaming
			router_sync = a3m.A3MRouterSync(  # type: ignore[attr-defined]
				client=self._a3m_router.client
			)
			response = router_sync.chat(
				messages=a3m_messages,
				model=self.model,
				max_tokens=self.max_output_tokens,
			)

			if stream:
				return self._stream_response(response)
			return response.choices[0].message.content

		except Exception as e:
			logger.error(f'A3M Router error: {e}')
			raise ModelProviderError(f'A3M Router generation failed: {e}') from e

	def _stream_response(self, response: Any) -> Any:
		"""Stream response from A3M Router."""
		for chunk in response:
			if chunk.choices[0].delta.content:
				yield chunk.choices[0].delta.content

	async def generate_async(self, messages: list[BaseMessage]) -> str:
		"""Async generate response from A3M Router."""
		import asyncio

		try:
			a3m_messages = self.messages_to_dict(messages)
			response = await asyncio.wait_for(
				self._a3m_router.chat(messages=a3m_messages, model=self.model),
				timeout=120,
			)
			return response.choices[0].message.content
		except TimeoutError as e:
			raise ModelRateLimitError(f'A3M Router timeout after 120s: {e}') from e
		except Exception as e:
			logger.error(f'A3M Router async error: {e}')
			raise ModelProviderError(f'A3M Router async generation failed: {e}') from e

	def get_cost(self) -> float | None:
		"""Get cost of last response if available."""
		return None  # A3M Router tracks cost internally

	def get_token_usage(self) -> dict[str, int] | None:
		"""Get token usage of last response if available."""
		return None  # A3M Router tracks usage internally
