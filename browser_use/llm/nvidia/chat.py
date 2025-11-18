from __future__ import annotations

import json
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
from browser_use.llm.nvidia.serializer import NvidiaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatNvidia(BaseChatModel):
	"""NVIDIA NIM /chat/completions wrapper via Brev (OpenAI-compatible)."""

	model: str = 'nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-35fbb28ZU7i7wmP1q1cSvS7JA6U'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None
	frequency_penalty: float | None = None
	presence_penalty: float | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.brev.dev/v1'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	@property
	def provider(self) -> str:
		return 'nvidia'

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
		NVIDIA NIM ainvoke supports:
		1. Regular text/multi-turn conversation
		2. Function Calling (tools)
		3. JSON Output (response_format)
		"""
		client = self._client()
		nvidia_messages = NvidiaMessageSerializer.serialize_messages(messages)
		common: dict[str, Any] = {}

		if self.temperature is not None:
			common['temperature'] = self.temperature
		if self.max_tokens is not None:
			common['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			common['top_p'] = self.top_p
		if self.seed is not None:
			common['seed'] = self.seed
		if self.frequency_penalty is not None:
			common['frequency_penalty'] = self.frequency_penalty
		if self.presence_penalty is not None:
			common['presence_penalty'] = self.presence_penalty
		if stop:
			common['stop'] = stop

		# ① Regular multi-turn conversation/text output
		if output_format is None and not tools:
			try:
				# Brev requires streaming mode
				stream = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=nvidia_messages,  # type: ignore
					stream=True,
					**common,
				)

				# Collect streaming response
				full_response = ""
				async for chunk in stream:
					if chunk.choices and len(chunk.choices) > 0:
						delta = chunk.choices[0].delta
						if delta.content:
							full_response += delta.content

				return ChatInvokeCompletion(
					completion=full_response,
					usage=None,
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		# ② JSON Output path (Cerebras-style: prompt-based, no function calling)
		# Brev doesn't support function calling, so we use prompt engineering
		if output_format is not None and hasattr(output_format, 'model_json_schema'):
			try:
				import re

				# Get the schema to guide the model
				schema = output_format.model_json_schema()
				schema_str = json.dumps(schema, indent=2)

				# Create a prompt that asks for the specific JSON structure
				json_prompt = f"""

Please respond with a JSON object that follows this exact schema:
{schema_str}

Your response must be valid JSON only, no other text."""

				# Add the JSON prompt to the last user message
				if nvidia_messages and nvidia_messages[-1]['role'] == 'user':
					if isinstance(nvidia_messages[-1]['content'], str):
						nvidia_messages[-1]['content'] += json_prompt
					elif isinstance(nvidia_messages[-1]['content'], list):
						nvidia_messages[-1]['content'].append({'type': 'text', 'text': json_prompt})
				else:
					# Add as a new user message
					nvidia_messages.append({'role': 'user', 'content': json_prompt})

				# Brev requires streaming mode
				stream = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=nvidia_messages,  # type: ignore
					stream=True,
					**common,
				)

				# Collect streaming response
				full_content = ""
				async for chunk in stream:
					if chunk.choices and len(chunk.choices) > 0:
						delta = chunk.choices[0].delta
						if delta.content:
							full_content += delta.content

				if not full_content:
					raise ModelProviderError('Empty JSON content in NVIDIA response', model=self.name)

				# Try to extract JSON from the response using regex
				json_match = re.search(r'\{.*\}', full_content, re.DOTALL)
				if json_match:
					json_str = json_match.group(0)
				else:
					json_str = full_content

				parsed = output_format.model_validate_json(json_str)
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

		raise ModelProviderError('No valid ainvoke execution path for NVIDIA LLM', model=self.name)
