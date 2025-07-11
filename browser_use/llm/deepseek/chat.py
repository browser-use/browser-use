from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import AsyncOpenAI, APIError, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.deepseek.serializer import DeepSeekMessageSerializer
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.schema import SchemaOptimizer          # ✅ 与 Anthropic 共用
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar("T", bound=BaseModel)


@dataclass
class ChatDeepSeek(BaseChatModel):
    """DeepSeek /chat/completions 封装（OpenAI-compatible）。"""

    model: str = "deepseek-chat"

    # 生成参数
    max_tokens: int | None = None
    temperature: float | None = None

    # 连接参数
    api_key: str | None = None
    base_url: str | httpx.URL | None = "https://api.deepseek.com/v1"
    timeout: float | httpx.Timeout | None = None
    client_params: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    @property
    def provider(self) -> str:  # 供 browser-use 判断
        return "deepseek"

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

    # ---------------------- 核心调用接口 -------------------------------- #
    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T] | None = None,
        tools: list[dict[str, Any]] | None = None,
        stop: list[str] | None = None,          # beta 对话前缀支持
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        """
        DeepSeek ainvoke 支持:
        1. 普通文本/多轮对话
        2. Function Calling
        3. JSON Output (response_format)
        4. 对话前缀续写 (beta, prefix, stop)
        """
        client = self._client()
        ds_messages = DeepSeekMessageSerializer.serialize_messages(messages)
        common: dict[str, Any] = {}
        if self.temperature is not None:
            common["temperature"] = self.temperature
        if self.max_tokens is not None:
            common["max_tokens"] = self.max_tokens

        # 若检测到 beta 对话前缀续写
        if self.base_url and str(self.base_url).endswith("/beta"):
            # 最后一个 assistant 必须 prefix
            if ds_messages and ds_messages[-1].get("role") == "assistant":
                ds_messages[-1]["prefix"] = True
            if stop:
                common["stop"] = stop

        # 普通 Function Calling 路径
        if output_format is None and (not tools):
            try:
                resp = await client.chat.completions.create(
                    model=self.model,
                    messages=ds_messages,
                    **common,
                )
                return ChatInvokeCompletion(
                    completion=resp.choices[0].message.content or "",
                    usage=None,
                )
            except RateLimitError as e:
                raise ModelRateLimitError(str(e), model=self.name) from e
            except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
                raise ModelProviderError(str(e), model=self.name) from e
            except Exception as e:
                raise ModelProviderError(str(e), model=self.name) from e

        # 若 Function Calling 路径 (有 tools/自动工具推理)
        if tools or (output_format and hasattr(output_format, "model_json_schema")):
            try:
                call_tools = tools
                tool_choice = None
                if output_format and hasattr(output_format, "model_json_schema"):
                    # output_format 存在，构造 function 工具 (自动推理工具名和 schema)
                    tool_name = output_format.__name__
                    schema = SchemaOptimizer.create_optimized_json_schema(output_format)
                    schema.pop("title", None)
                    call_tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "description": f"Return a JSON object of type {tool_name}",
                                "parameters": schema,
                            },
                        }
                    ]
                    tool_choice = {"type": "function", "function": {"name": tool_name}}
                resp = await client.chat.completions.create(
                    model=self.model,
                    messages=ds_messages,
                    tools=call_tools,
                    tool_choice=tool_choice,
                    **common,
                )
                msg = resp.choices[0].message
                if not msg.tool_calls:
                    raise ValueError("Expected tool_calls in response but got none")
                raw_args = msg.tool_calls[0].function.arguments
                if isinstance(raw_args, str):
                    parsed = json.loads(raw_args)
                else:
                    parsed = raw_args
                return ChatInvokeCompletion(
                    completion=output_format.model_validate(parsed),
                    usage=None,
                )
            except RateLimitError as e:
                raise ModelRateLimitError(str(e), model=self.name) from e
            except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
                raise ModelProviderError(str(e), model=self.name) from e
            except Exception as e:
                raise ModelProviderError(str(e), model=self.name) from e

        # JSON Output 路径 (官方 response_format)
        if output_format is not None and hasattr(output_format, "model_json_schema"):
            # 符合 deepseek 官方 JSON Output
            try:
                resp = await client.chat.completions.create(
                    model=self.model,
                    messages=ds_messages,
                    response_format={"type": "json_object"},
                    **common,
                )
                content = resp.choices[0].message.content
                if not content:
                    raise ModelProviderError("Empty JSON content in DeepSeek response", model=self.name)
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
