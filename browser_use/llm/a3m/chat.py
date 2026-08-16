"""
ChatA3M - A3M Router chat model wrapper for browser-use.

Provides intelligent LLM routing for browser automation with:
- Automatic routing to cheapest capable model
- Stealth mode for anti-detection
- Parallel ensemble for reliability
- Parallel ensemble for reliable extraction

Requires the `adaptive-memory-multi-model-router` package:
    pip install adaptive-memory-multi-model-router

Usage:
    from browser_use import Agent
    from browser_use.llm.a3m import ChatA3M

    agent = Agent(
        task="Fill out this job application form",
        llm=ChatA3M(model="auto", stealth=True),
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

from .serializer import A3MMessageSerializer

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatA3M(BaseChatModel):
    """
    A3M Router - Intelligent routing for browser automation.

    Attributes:
        model: Model to use. Use "auto" for automatic routing.
        api_key: A3M API key (optional, uses env A3M_API_KEY if not provided).
        stealth: Enable stealth mode for anti-detection.
        parallel_ensemble: Number of providers to run in parallel.

        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
    """

    model: str = "auto"
    api_key: str | None = None
    stealth: bool = True
    parallel_ensemble: int = 1
    temperature: float | None = 0.0
    max_tokens: int | None = 4096

    _a3m_router: Any = field(default=None, init=False, repr=False)
    _provider_name: str = field(default='a3m', init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize A3M router."""
        try:
            from a3m import A3MRouter

            self._a3m_router = A3MRouter(
                model=self.model,
                stealth=self.stealth,
                parallel_ensemble=self.parallel_ensemble,
            )
            logger.debug(
                'ChatA3M initialized: model=%s, stealth=%s, ensemble=%s',
                self.model,
                self.stealth,
                self.parallel_ensemble,
            )
        except ImportError as e:
            raise ModelProviderError(
                message=f"A3M Router not installed. Run: pip install adaptive-memory-multi-model-router. Error: {e}",
                model=self.model,
            ) from e

    @property
    def provider(self) -> str:
        return self._provider_name

    @property
    def name(self) -> str:
        return f"a3m-{self.model}"

    @staticmethod
    def _parse_usage(response: Any) -> ChatInvokeUsage | None:
        """Extract token usage from an A3M response."""
        usage = getattr(response, 'usage', None)
        if usage is None:
            return None

        prompt_tokens = getattr(usage, 'prompt_tokens', 0) or 0
        completion_tokens = getattr(usage, 'completion_tokens', 0) or 0

        return ChatInvokeUsage(
            prompt_tokens=prompt_tokens,
            prompt_cached_tokens=None,
            prompt_cache_creation_tokens=None,
            prompt_image_tokens=None,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T],
        **kwargs: Any,
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T] | None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        """Invoke A3M Router with automatic provider selection."""
        from a3m.models import RoutingDecision

        # Serialize messages for A3M
        a3m_messages = A3MMessageSerializer.serialize(messages)

        # Build request params
        params: dict[str, Any] = {
            'model': self.model,
            'messages': a3m_messages,
            'temperature': self.temperature or 0.0,
            'max_tokens': self.max_tokens or 4096,
        }

        if self.api_key:
            params['api_key'] = self.api_key

        # Add output format if specified
        if output_format is not None:
            schema = SchemaOptimizer.create_optimized_json_schema(output_format)
            params['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'agent_output',
                    'strict': True,
                    'schema': schema,
                },
            }

        # Route the request through A3M (run sync call in executor to avoid blocking event loop)
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            result: RoutingDecision = await loop.run_in_executor(
                None, lambda: self._a3m_router.route(**params)
            )
        except Exception as e:
            error_msg = str(e)
            if 'rate limit' in error_msg.lower() or '429' in error_msg:
                raise ModelRateLimitError(
                    message=error_msg,
                    model=self.name,
                ) from e
            raise ModelProviderError(
                message=error_msg,
                model=self.name,
            ) from e

        # Extract response content
        content = result.content if hasattr(result, 'content') else str(result)
        usage = self._parse_usage(result) if hasattr(result, 'usage') else None
        stop_reason = getattr(result, 'finish_reason', None)

        # Get thinking content if available
        thinking: str | None = None
        if hasattr(result, 'thinking'):
            thinking = result.thinking

        if output_format is not None:
            if not content:
                raise ModelProviderError(
                    message='Model returned empty content for structured output request',
                    status_code=500,
                    model=self.name,
                )
            parsed = output_format.model_validate_json(content)
            return ChatInvokeCompletion(
                completion=parsed,
                thinking=thinking,
                usage=usage,
                stop_reason=stop_reason,
            )

        return ChatInvokeCompletion(
            completion=content,
            thinking=thinking,
            usage=usage,
            stop_reason=stop_reason,
        )

    def get_cost(self) -> dict[str, Any]:
        """Get cost statistics from A3M router."""
        if self._a3m_router and hasattr(self._a3m_router, 'get_cost'):
            return self._a3m_router.get_cost()
        return {}

    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics from A3M router."""
        if self._a3m_router and hasattr(self._a3m_router, 'get_stats'):
            return self._a3m_router.get_stats()
        return {}
