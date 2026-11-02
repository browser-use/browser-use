from __future__ import annotations

import json
import os
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
	Timeout,
)
from pydantic import BaseModel, ValidationError

from browser_use.llm.base import BaseChatModel
from browser_use.llm.deepseek.serializer import DeepSeekMessageSerializer
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


def _repair_json_control_chars(text: str) -> str:
	"""Escape raw control characters inside JSON string literals.

	DeepSeek v4 occasionally emits unescaped control characters (e.g. literal
	newlines) inside JSON string values, which is invalid JSON.
	"""
	out: list[str] = []
	in_string = False
	escaped = False
	for ch in text:
		if in_string:
			if escaped:
				out.append(ch)
				escaped = False
			elif ch == '\\':
				out.append(ch)
				escaped = True
			elif ch == '"':
				out.append(ch)
				in_string = False
			elif ord(ch) < 0x20:
				out.append(f'\\u{ord(ch):04x}')
			else:
				out.append(ch)
		else:
			out.append(ch)
			if ch == '"':
				in_string = True
	return ''.join(out)


def _strip_json_wrappers(text: str) -> str:
	"""Remove markdown fences or surrounding prose from a JSON response."""
	cleaned = text.strip()
	if cleaned.startswith('```'):
		lines = cleaned.splitlines()
		if lines and lines[0].startswith('```'):
			lines = lines[1:]
		if lines and lines[-1].strip() == '```':
			lines = lines[:-1]
		cleaned = '\n'.join(lines).strip()

	start = cleaned.find('{')
	end = cleaned.rfind('}')
	if start != -1 and end > start:
		cleaned = cleaned[start : end + 1]
	return cleaned


def _parse_json_output(output_format: type[T], content: str) -> T:
	"""Parse JSON output, tolerating fences and raw control characters."""
	last_error: ValidationError | None = None
	candidates = [content, _strip_json_wrappers(content)]
	for candidate in candidates:
		try:
			return output_format.model_validate_json(candidate)
		except ValidationError as e:
			last_error = e

	repaired = _repair_json_control_chars(candidates[-1])
	if repaired != candidates[-1]:
		try:
			return output_format.model_validate_json(repaired)
		except ValidationError as e:
			last_error = e

	if last_error is not None:
		raise last_error
	raise ValueError('Could not parse JSON output')


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

	@staticmethod
	def _is_reasoning_model(model: str) -> bool:
		"""Check if the model is a DeepSeek reasoning model that doesn't support tool_choice."""
		model_lower = model.lower()
		return any(kw in model_lower for kw in ['reasoner', '/thinking', '-r1', '-thinking', '-v4'])

	@property
	def provider(self) -> str:
		return 'deepseek'

	def _client(self) -> AsyncOpenAI:
		api_key = self.api_key or os.getenv('DEEPSEEK_API_KEY')
		if not api_key:
			raise ModelProviderError(
				message='Missing DeepSeek API key. Set DEEPSEEK_API_KEY or pass api_key.',
				status_code=401,
				model=self.name,
			)

		return AsyncOpenAI(
			api_key=api_key,
			base_url=str(self.base_url) if self.base_url is not None else None,
			timeout=Timeout(**self.timeout.as_dict()) if isinstance(self.timeout, httpx.Timeout) else self.timeout,
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
		1. Regular text/multi-turn conversation
		2. Function Calling
		3. JSON Output (response_format)
		4. Conversation prefix continuation (beta, prefix, stop)
		"""
		client = self._client()
		ds_messages = DeepSeekMessageSerializer.serialize_messages(messages)
		common = self._request_kwargs()

		# DeepSeek v4 models default to thinking mode, which breaks strict
		# function-calling schema adherence; disable it for reasoning models
		# unless the caller explicitly opted into thinking mode.
		if self._is_reasoning_model(self.model) and not self.thinking:
			common['extra_body'] = {'thinking': {'type': 'disabled'}}

		# Beta conversation prefix continuation (see official documentation)
		if self.base_url and str(self.base_url).endswith('/beta'):
			# The last assistant message must have prefix
			if ds_messages and isinstance(ds_messages[-1], dict) and ds_messages[-1].get('role') == 'assistant':
				ds_messages[-1]['prefix'] = True
			if stop:
				common['stop'] = stop

		# ① Regular multi-turn conversation/text output
		if output_format is None and not tools:
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

		# ①b JSON Output path — DeepSeek reasoning models (v4 etc.) cannot
		# reliably follow the function-calling schema (they emit flat tool args),
		# so route them through strict JSON output mode instead.
		if (
			not tools
			and output_format is not None
			and hasattr(output_format, 'model_json_schema')
			and self._is_reasoning_model(self.model)
		):
			try:
				# DeepSeek requires the prompt to mention JSON when response_format
				# is json_object, otherwise it may emit whitespace until the token
				# limit. Include the schema so the model knows the expected shape.
				schema = output_format.model_json_schema()
				json_instruction = (
					'Respond with a single valid JSON object only. '
					'The first character must be "{" and the last character must be "}". '
					'Do not include markdown fences, comments, trailing commas, or any prose outside the JSON object. '
					'Every string value MUST be valid JSON: escape every double quote inside a string as \\", '
					'every backslash as \\\\, and every newline as \\n. '
					'Never place raw JSON, HTML, or multi-line code inside "thinking". '
					'When quoting text inside "thinking", prefer single quotes. '
					'When writing JavaScript for "evaluate", prefer single quotes or backticks so double quotes do not need escaping. '
					'The "action" field is REQUIRED and must be a non-empty array; never return only '
					'"thinking", "memory", or "next_goal". If unsure, use the "wait" action. '
					f'The JSON object must conform to this schema:\n{json.dumps(schema, ensure_ascii=False)}'
				)
				json_messages = [dict(message) for message in ds_messages]
				if json_messages and json_messages[0].get('role') == 'system':
					json_messages[0]['content'] = f'{json_messages[0].get("content", "")}\n\n{json_instruction}'
				else:
					json_messages.insert(0, {'role': 'system', 'content': json_instruction})

				last_error: ValidationError | None = None
				for attempt in range(2):
					resp = await client.chat.completions.create(  # type: ignore
						model=self.model,
						messages=json_messages,  # type: ignore
						response_format={'type': 'json_object'},
						**common,
					)
					choice = resp.choices[0]
					if getattr(choice, 'finish_reason', None) == 'length':
						cap = f'max_tokens={self.max_tokens}' if self.max_tokens is not None else "the model's output token limit"
						raise ModelOutputTruncatedError(
							message=(
								f'DeepSeek output was truncated at {cap}; the structured output is incomplete. '
								'Increase max_tokens or request shorter output.'
							),
							model=self.name,
						)

					message = choice.message
					content = message.content
					if not content:
						if attempt == 0:
							json_messages.append(
								{
									'role': 'user',
									'content': (
										'Your previous response was empty. Return a single valid JSON object only. '
										'The "action" field is required and must be a non-empty array.'
									),
								}
							)
							continue
						raise ModelProviderError('Empty JSON content in DeepSeek response', model=self.name)

					try:
						parsed = _parse_json_output(output_format, content)
					except ValidationError as e:
						last_error = e
						if attempt == 0:
							error_summary = str(e).splitlines()[0][:500]
							json_messages.extend(
								[
									{'role': 'assistant', 'content': content},
									{
										'role': 'user',
										'content': (
											f'Your previous response was invalid: {error_summary}\n'
											'Return the complete corrected JSON object only. '
											'The "action" field is required and must be a non-empty array. '
											'Escape every double quote inside string values as \\". '
											'Do not use markdown fences or prose.'
										),
									},
								]
							)
							continue
						raise

					reasoning = getattr(message, 'reasoning_content', None)
					return ChatInvokeCompletion(
						completion=parsed,
						thinking=str(reasoning) if reasoning else None,
						usage=None,
					)

				if last_error is not None:
					raise last_error
				raise ModelProviderError('Empty JSON content in DeepSeek response', model=self.name)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except ModelProviderError:
				raise
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
					tool_choice = {'type': 'function', 'function': {'name': tool_name}}
					# Reasoning models (deepseek-v4-pro, deepseek-reasoner, etc.) reject tool_choice
					if self._is_reasoning_model(self.model):
						tool_choice = None
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					tools=call_tools,  # type: ignore
					tool_choice=tool_choice,  # type: ignore
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
					messages=ds_messages,  # type: ignore
					response_format={'type': 'json_object'},
					**common,
				)
				content = resp.choices[0].message.content
				if not content:
					raise ModelProviderError('Empty JSON content in DeepSeek response', model=self.name)
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

		raise ModelProviderError('No valid ainvoke execution path for DeepSeek LLM', model=self.name)
