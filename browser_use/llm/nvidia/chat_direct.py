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
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.nvidia.serializer_direct import NvidiaDirectMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatNvidiaDirect(BaseChatModel):
	"""NVIDIA NIM direct API wrapper (OpenAI-compatible) with multimodal support.

	Note: Uses prompt engineering for structured output since most NVIDIA models
	don't support function calling via the public API.
	"""

	model: str = 'nvidia/llama-3.1-nemotron-70b-instruct'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None
	frequency_penalty: float | None = None
	presence_penalty: float | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://integrate.api.nvidia.com/v1'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	@property
	def provider(self) -> str:
		return 'nvidia-direct'

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

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is not None:
			usage = ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				prompt_cached_tokens=None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
				completion_tokens=response.usage.completion_tokens,
				total_tokens=response.usage.total_tokens,
			)
		else:
			usage = None
		return usage

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: None = None,
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T],
	) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		NVIDIA Direct API ainvoke supports:
		1. Regular text/multi-turn conversation
		2. Multimodal input (vision models)
		3. JSON Output (prompt engineering, similar to Cerebras)

		Note: Function calling is not supported by NVIDIA models on the public API.
		"""
		client = self._client()
		nvidia_messages = NvidiaDirectMessageSerializer.serialize_messages(messages)
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

		# ① Regular multi-turn conversation/text output
		if output_format is None:
			try:
				# Debug logging
				import sys
				print(f'[DEBUG] Calling NVIDIA API with:', file=sys.stderr)
				print(f'  model={self.model}', file=sys.stderr)
				print(f'  messages count={len(nvidia_messages)}', file=sys.stderr)
				print(f'  common={common}', file=sys.stderr)

				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=nvidia_messages,  # type: ignore
					**common,
				)
				usage = self._get_usage(resp)
				return ChatInvokeCompletion(
					completion=resp.choices[0].message.content or '',
					usage=usage,
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		# ② JSON Output path (Cerebras-style: prompt-based, no function calling)
		# NVIDIA Direct API doesn't support function calling for most models
		if output_format is not None and hasattr(output_format, 'model_json_schema'):
			try:
				import re
				import sys

				# Debug logging
				print(f'[DEBUG] Using JSON output path for {output_format.__name__}', file=sys.stderr)

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

				print(f'[DEBUG] Calling NVIDIA API for JSON output:', file=sys.stderr)
				print(f'  model={self.model}', file=sys.stderr)
				print(f'  messages count={len(nvidia_messages)}', file=sys.stderr)
				print(f'  common={common}', file=sys.stderr)

				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=nvidia_messages,  # type: ignore
					**common,
				)

				content = resp.choices[0].message.content
				if not content:
					raise ModelProviderError('Empty JSON content in NVIDIA response', model=self.name)

				usage = self._get_usage(resp)

				# Try to extract JSON from the response using regex
				json_match = re.search(r'\{.*\}', content, re.DOTALL)
				if json_match:
					json_str = json_match.group(0)
				else:
					json_str = content

				parsed = output_format.model_validate_json(json_str)
				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		raise ModelProviderError('No valid ainvoke execution path for NVIDIA Direct LLM', model=self.name)
