from __future__ import annotations

import json
import re
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
from browser_use.llm.deepseek.serializer import DeepSeekMessageSerializer
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, ContentPartTextParam, SystemMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)

_JSON_FENCE_RE = re.compile(r'\A```[ \t]*(?:json)?[ \t]*\r?\n(?P<body>.*?)\r?\n?```[ \t]*\Z', re.IGNORECASE | re.DOTALL)


def _unwrap_json_content(content: str) -> str:
	"""Strip markdown code fences that LLMs often wrap around JSON."""
	text = content.strip()
	match = _JSON_FENCE_RE.fullmatch(text)
	if match:
		return match.group('body').strip()
	return text


@dataclass
class ChatDeepSeek(BaseChatModel):
	"""DeepSeek /chat/completions wrapper (OpenAI-compatible)."""

	model: str = 'deepseek-v4-flash'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.deepseek.com/v1'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	thinking: bool = False

	@property
	def provider(self) -> str:
		return 'deepseek'

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

	def _supports_thinking(self) -> bool:
		return 'deepseek-v4' in self.model.lower()

	def _request_kwargs(self) -> dict[str, Any]:
		common: dict[str, Any] = {}

		if self.temperature is not None:
			common['temperature'] = self.temperature
		if self.max_tokens is not None:
			common['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			common['top_p'] = self.top_p
		if self.seed is not None:
			common['seed'] = self.seed

		if self._supports_thinking():
			common['extra_body'] = {
				'thinking': {'type': 'enabled' if self.thinking else 'disabled'},
			}
		return common

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: None = None,
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T],
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		DeepSeek ainvoke supports:
		1. Structured JSON Output (response_format)
		2. Regular text/multi-turn conversation
		3. Function Calling (when tools are provided without output_format)
		4. Conversation prefix continuation (beta, prefix, stop)
		"""
		client = self._client()
		common = self._request_kwargs()

		# ① Structured Output path (official response_format for structured models)
		if output_format is not None and hasattr(output_format, 'model_json_schema'):
			try:
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)
				schema_instruction = (
					f'You must respond with a single JSON object matching this schema exactly:\n{json.dumps(schema)}'
				)
				# Place schema instruction in system prompt to preserve prefix continuation on assistant turns
				formatted_messages: list[BaseMessage] = list(messages)
				if formatted_messages and isinstance(formatted_messages[0], SystemMessage):
					orig_content = formatted_messages[0].content
					if isinstance(orig_content, str):
						new_content = f'{orig_content}\n\n{schema_instruction}'
					elif isinstance(orig_content, list):
						new_content = [*orig_content, ContentPartTextParam(text=f'\n\n{schema_instruction}', type='text')]
					else:
						new_content = schema_instruction
					formatted_messages[0] = SystemMessage(content=new_content)
				else:
					formatted_messages.insert(0, SystemMessage(content=schema_instruction))

				ds_messages = DeepSeekMessageSerializer.serialize_messages(formatted_messages)

				# Beta conversation prefix continuation
				if self.base_url and str(self.base_url).endswith('/beta'):
					if ds_messages and isinstance(ds_messages[-1], dict) and ds_messages[-1].get('role') == 'assistant':
						ds_messages[-1]['prefix'] = True
					if stop:
						common['stop'] = stop

				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					response_format={'type': 'json_object'},
					**common,
				)
				content = resp.choices[0].message.content
				if not content:
					raise ModelProviderError('Empty JSON content in DeepSeek response', model=self.name)
				clean_content = _unwrap_json_content(content)
				parsed = output_format.model_validate_json(clean_content)
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

		# Serialize messages for non-structured paths
		ds_messages = DeepSeekMessageSerializer.serialize_messages(messages)

		# Beta conversation prefix continuation (see official documentation)
		if self.base_url and str(self.base_url).endswith('/beta'):
			# The last assistant message must have prefix
			if ds_messages and isinstance(ds_messages[-1], dict) and ds_messages[-1].get('role') == 'assistant':
				ds_messages[-1]['prefix'] = True
			if stop:
				common['stop'] = stop

		# ② Regular multi-turn conversation/text output
		if not tools:
			try:
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
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

		# ③ Function Calling path (when tools are explicitly provided without output_format)
		try:
			resp = await client.chat.completions.create(  # type: ignore
				model=self.model,
				messages=ds_messages,  # type: ignore
				tools=tools,  # type: ignore
				**common,
			)
			msg = resp.choices[0].message
			if not msg.tool_calls:
				raise ValueError('Expected tool_calls in response but got none')
			raw_args = msg.tool_calls[0].function.arguments
			if isinstance(raw_args, str):
				parsed = json.loads(raw_args)
			else:
				parsed = raw_args
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
