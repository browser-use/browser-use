from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar, overload

from mistralai import Mistral
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.mistral.serializer import MistralMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatMistral(BaseChatModel):
	"""Mistral AI chat model wrapper."""

	model: str = 'mistral-large-latest'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	random_seed: int | None = None

	# Connection parameters
	api_key: str | None = None
	endpoint: str | None = None
	timeout: int = 120

	@property
	def provider(self) -> str:
		return 'mistral'

	def _client(self) -> Mistral:
		client_params: dict[str, Any] = {
			'api_key': self.api_key,
			'timeout_ms': self.timeout * 1000,
		}
		if self.endpoint:
			client_params['server_url'] = self.endpoint
		return Mistral(**client_params)

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
		Mistral ainvoke supports:
		1. Regular text/multi-turn conversation
		2. Function Calling (tools)
		3. JSON Output (response_format)
		"""
		client = self._client()
		mistral_messages = MistralMessageSerializer.serialize_messages(messages)
		
		common: dict[str, Any] = {
			'model': self.model,
			'messages': mistral_messages,
		}

		if self.temperature is not None:
			common['temperature'] = self.temperature
		if self.max_tokens is not None:
			common['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			common['top_p'] = self.top_p
		if self.random_seed is not None:
			common['random_seed'] = self.random_seed
		if stop is not None:
			common['stop'] = stop

		try:
			# Handle structured output
			if output_format is not None:
				# Use function calling for structured output
				tool_name = output_format.__name__
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)
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
				common['tools'] = call_tools
				common['tool_choice'] = 'any'
				
				response = await client.chat.complete_async(**common)
				
				choice = response.choices[0]
				if not choice.message.tool_calls:
					raise ModelProviderError('Expected tool_calls in response but got none', model=self.name)
				
				raw_args = choice.message.tool_calls[0].function.arguments
				if isinstance(raw_args, str):
					parsed = json.loads(raw_args)
				else:
					parsed = raw_args
				
				return ChatInvokeCompletion(
					completion=output_format.model_validate(parsed),
					usage=None,
				)

			# Handle tool calls
			elif tools is not None and len(tools) > 0:
				common['tools'] = tools
				response = await client.chat.complete_async(**common)
				
				choice = response.choices[0]
				content_str = choice.message.content or ''
				
				return ChatInvokeCompletion(
					completion=content_str,
					usage=None,
				)

			# Handle regular text completion
			else:
				response = await client.chat.complete_async(**common)
				
				content = response.choices[0].message.content
				if not content:
					raise ModelProviderError('Mistral returned empty content', model=self.name)
				
				return ChatInvokeCompletion(
					completion=content,
					usage=None,
				)

		except Exception as e:
			error_msg = str(e).lower()
			if 'rate limit' in error_msg or 'quota' in error_msg:
				raise ModelRateLimitError(str(e), model=self.name) from e
			raise ModelProviderError(str(e), model=self.name) from e
