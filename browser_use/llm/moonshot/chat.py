from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.moonshot.serializer import MoonshotMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatMoonshot(BaseChatModel):
    """Moonshot AI (Kimi) /chat/completions wrapper (OpenAI-compatible)."""

    model: str = 'moonshot-v1-8k'

    # Generation parameters
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    # Connection parameters
    api_key: str | None = None
    base_url: str | httpx.URL | None = 'https://api.moonshot.cn/v1'
    timeout: float | httpx.Timeout | None = None
    client_params: dict[str, Any] | None = None

    @property
    def provider(self) -> str:
        return 'moonshot'

    def _client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            **(self.client_params or {}),
        )

    @property
    def name(self) -> str:
        return self.model

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: None = None,
        tools: list[dict[str, Any]] | None = None,
        stop: list[str] | None = None,
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T],
        tools: list[dict[str, Any]] | None = None,
        stop: list[str] | None = None,
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
            self,
            messages: list[BaseMessage],
            output_format: type[T] | None = None,
            tools: list[dict[str, Any]] | None = None,
            stop: list[str] | None = None,
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        """
        Moonshot AI (Kimi) ainvoke supports:
        1. Regular text/multi-turn conversation
        2. Function Calling
        3. JSON Output (response_format)
        """
        client = self._client()
        ms_messages = MoonshotMessageSerializer.serialize_messages(messages)
        common: dict[str, Any] = {}

        if self.temperature is not None:
            common['temperature'] = self.temperature
        if self.max_tokens is not None:
            common['max_tokens'] = self.max_tokens
        if self.top_p is not None:
            common['top_p'] = self.top_p
        if self.seed is not None:
            common['seed'] = self.seed

        # ① Regular multi-turn conversation/text output
        if output_format is None and not tools:
            try:
                resp = await client.chat.completions.create(  # type: ignore
                    model=self.model,
                    messages=ms_messages,  # type: ignore
                    **common,
                )
                return ChatInvokeCompletion(
                    completion=resp.choices[0].message.content or '',
                    usage=None,
                )
            except RateLimitError as e:
                raise ModelRateLimitError(str(e), model=self.name) from e
            except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
                raise ModelProviderError(str(e), model=self.name) from e
            except Exception as e:
                raise ModelProviderError(str(e), model=self.name) from e

        # ② Function Calling path (with tools or output_format)
        if tools or (output_format is not None and hasattr(output_format, 'model_json_schema')):
            try:
                call_tools = tools
                tool_choice = None
                if output_format is not None and hasattr(output_format, 'model_json_schema'):
                    tool_name = output_format.__name__
                    schema = SchemaOptimizer.create_optimized_json_schema(
                        output_format)
                    schema.pop('title', None)
                    call_tools = [
                        {
                            'type': 'function',
                            'function': {
                                'name': tool_name,
                                'description': f'Return a JSON object of type {tool_name}',
                                'parameters': schema,
                            },
                        }
                    ]
                    tool_choice = {'type': 'function',
                                   'function': {'name': tool_name}}

                # Log request details
                logger.info("[Moonshot] Making request with:")
                logger.info(f"  - model: {self.model}")
                logger.info(
                    f"  - output_format: {output_format.__name__ if output_format else None}")
                logger.info(f"  - tools provided: {bool(tools)}")
                logger.info(
                    f"  - call_tools count: {len(call_tools) if call_tools else 0}")
                logger.info(f"  - tool_choice: {tool_choice}")
                logger.info(f"  - messages count: {len(ms_messages)}")
                if call_tools:
                    logger.info(
                        f"  - tool schemas: {json.dumps(call_tools, indent=2)}")

                resp = await client.chat.completions.create(  # type: ignore
                    model=self.model,
                    messages=ms_messages,  # type: ignore
                    tools=call_tools,  # type: ignore
                    tool_choice=tool_choice,  # type: ignore
                    **common,
                )
                msg = resp.choices[0].message

                # Log response details
                logger.info("[Moonshot] Response received:")
                logger.info(f"  - has tool_calls: {bool(msg.tool_calls)}")
                logger.info(
                    f"  - tool_calls count: {len(msg.tool_calls) if msg.tool_calls else 0}")
                logger.info(
                    f"  - content: {msg.content[:200] if msg.content else None}")
                logger.info(
                    f"  - finish_reason: {resp.choices[0].finish_reason}")

                if msg.tool_calls:
                    for i, tc in enumerate(msg.tool_calls):
                        logger.info(
                            f"  - tool_call[{i}].name: {tc.function.name}")
                        logger.info(
                            f"  - tool_call[{i}].arguments: {tc.function.arguments[:200] if isinstance(tc.function.arguments, str) else str(tc.function.arguments)[:200]}")

                # If no tool calls, handle based on whether output_format is required
                if not msg.tool_calls:
                    # If output_format is specified, try to parse JSON from content as fallback
                    if output_format is not None:
                        logger.warning(
                            f"[Moonshot] No tool_calls returned, attempting to parse JSON from content...")  # noqa: F541
                        logger.info(
                            f"[Moonshot] Response content: {msg.content}")

                        # Moonshot may return JSON directly in content instead of tool_calls
                        if msg.content:
                            try:
                                # Try to parse the content as JSON
                                parsed = json.loads(msg.content)
                                logger.info(
                                    "[Moonshot] Successfully parsed JSON from content!")
                                return ChatInvokeCompletion(
                                    completion=output_format.model_validate(
                                        parsed),
                                    usage=None,
                                )
                            except (json.JSONDecodeError, Exception) as parse_error:
                                logger.error(
                                    f"[Moonshot] Failed to parse JSON from content: {parse_error}")
                                logger.error(
                                    f"[Moonshot] Content was: {msg.content[:500]}")

                        logger.error(
                            f"[Moonshot] ERROR: output_format={output_format.__name__} was specified but no tool_calls in response and content is not valid JSON!")
                        logger.error(
                            f"[Moonshot] Finish reason: {resp.choices[0].finish_reason}")
                        raise ValueError(
                            'Expected tool_calls in response but got none and content is not parseable JSON')
                    # Otherwise, return the text content (model chose not to call tools)
                    return ChatInvokeCompletion(
                        completion=msg.content or '',
                        usage=None,
                    )

                raw_args = msg.tool_calls[0].function.arguments
                if isinstance(raw_args, str):
                    parsed = json.loads(raw_args)
                else:
                    parsed = raw_args
                # --------- Fix: only use model_validate when output_format is not None ----------
                if output_format is not None:
                    return ChatInvokeCompletion(
                        completion=output_format.model_validate(parsed),
                        usage=None,
                    )
                else:
                    # If no output_format, return dict directly
                    return ChatInvokeCompletion(
                        completion=parsed,
                        usage=None,
                    )
            except RateLimitError as e:
                raise ModelRateLimitError(str(e), model=self.name) from e
            except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
                raise ModelProviderError(str(e), model=self.name) from e
            except Exception as e:
                raise ModelProviderError(str(e), model=self.name) from e

        # ③ JSON Output path (official response_format)
        if output_format is not None and hasattr(output_format, 'model_json_schema'):
            try:
                resp = await client.chat.completions.create(  # type: ignore
                    model=self.model,
                    messages=ms_messages,  # type: ignore
                    response_format={'type': 'json_object'},
                    **common,
                )
                content = resp.choices[0].message.content
                if not content:
                    raise ModelProviderError(
                        'Empty JSON content in Moonshot response', model=self.name)
                parsed = output_format.model_validate_json(content)
                return ChatInvokeCompletion(
                    completion=parsed,
                    usage=None,
                )
            except RateLimitError as e:
                raise ModelRateLimitError(str(e), model=self.name) from e
            except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
                raise ModelProviderError(str(e), model=self.name) from e
            except Exception as e:
                raise ModelProviderError(str(e), model=self.name) from e

        raise ModelProviderError(
            'No valid ainvoke execution path for Moonshot LLM', model=self.name)
