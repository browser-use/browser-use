"""
ChatA3M - A3M Router chat model wrapper for browser-use.

Provides intelligent LLM routing for browser automation with:
- Automatic routing to cheapest capable model
- Stealth mode for anti-detection
- Parallel ensemble for reliability

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

# pyright: reportInvalidTypeForm=false

import logging
from dataclasses import dataclass
from typing import Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatA3M(BaseChatModel):
	"""A3M Router chat model for browser-use.

	A3M Router provides intelligent LLM routing with:
	- Automatic routing to cheapest capable model
	- 80+ supported providers
	- EXP3 game theory-based exploration/exploitation
	- MVT rate-limit rotation

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
			import a3m  # type: ignore[attr-defined]

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

	@property
	def name(self) -> str:
		"""Return model name."""
		return self.model

	@overload
	def generate(self, messages: list[BaseMessage]) -> str: ...

	@overload
	def generate(self, messages: list[BaseMessage], stream: bool) -> Any: ...

	def generate(self, messages: list[BaseMessage], stream: bool = False) -> Any:
		"""Generate response from A3M Router."""
		try:
			import a3m  # type: ignore[attr-defined]

			from browser_use.llm.openai.serializer import OpenAIMessageSerializer

			a3m_messages = OpenAIMessageSerializer.serialize_messages(messages)

			router_sync = a3m.A3MRouterSync(  # type: ignore[attr-defined]
				client=self._a3m_router.client
			)
			response = router_sync.chat(
				messages=a3m_messages,
				model=self.model,
				max_tokens=self.max_output_tokens,
				stream=stream,
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

	@overload
	async def ainvoke(  # type: ignore[reportInvalidTypeForm]
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""Async invoke the A3M Router."""
		import asyncio

		try:
			from browser_use.llm.openai.serializer import OpenAIMessageSerializer

			a3m_messages = OpenAIMessageSerializer.serialize_messages(messages)

			# When output_format is provided, inject schema as a system message
			# since A3M Router uses OpenAI-compatible API
			if output_format is not None:
				schema_json = output_format.model_json_schema()
				schema_instruction = (
					f'\n\nIMPORTANT: Your response MUST be valid JSON matching this schema:\n'
					f'{schema_json}\n\nRespond ONLY with the JSON object, no additional text.'
				)
				# Prepend schema instruction to last user message
				for msg in reversed(a3m_messages):
					if msg.get('role') == 'user':
						msg_content = msg.get('content', '')
						if isinstance(msg_content, str):
							msg['content'] = msg_content + schema_instruction
						break

			response = await asyncio.wait_for(
				self._a3m_router.chat(
					messages=a3m_messages,
					model=self.model,
					max_tokens=self.max_output_tokens,
				),
				timeout=120,
			)

			content = response.choices[0].message.content or ''

			if output_format is not None:
				try:
					completion = output_format.model_validate_json(content)
					return ChatInvokeCompletion(completion=completion, usage=None)
				except Exception as e:
					raise ModelProviderError(
						message=f'A3M Router returned invalid JSON for structured output: {e}',
						model=self.name,
					) from e

			return ChatInvokeCompletion(completion=content, usage=None)

		except TimeoutError as e:
			raise ModelRateLimitError(f'A3M Router timeout after 120s: {e}') from e
		except ModelProviderError:
			raise
		except Exception as e:
			logger.error(f'A3M Router ainvoke error: {e}')
			raise ModelProviderError(f'A3M Router ainvoke failed: {e}') from e

	def get_cost(self) -> float | None:
		"""Get cost of last response if available."""
		return None  # A3M Router tracks cost internally

	def get_token_usage(self) -> dict[str, int] | None:
		"""Get token usage of last response if available."""
		return None  # A3M Router tracks usage internally
