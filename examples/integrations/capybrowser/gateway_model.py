"""Bounded JSON-object model adapter for an OpenAI-compatible gateway."""

import json
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openai import AsyncOpenAI, DefaultAsyncHttpxClient, omit

from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage


class GatewayModel:
	"""Keep model requests bounded and persist token counts without prompts."""

	provider = 'openai'

	def __init__(self, config_path: Path, usage_path: Path, *, max_calls: int = 10):
		if not config_path.is_absolute():
			raise ValueError('Model config path must be absolute.')
		if config_path.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
			raise ValueError('Model config must stay outside the checkout.')
		if stat.S_IMODE(config_path.stat().st_mode) & 0o077:
			raise ValueError('Model config must have private permissions.')
		config = json.loads(config_path.read_text())
		base_url = config['base_url'].rstrip('/')
		parts = urlsplit(base_url)
		if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
			raise ValueError('Model base URL must be a clean HTTPS URL.')
		if (
			not isinstance(config['model'], str)
			or not config['model']
			or not isinstance(config['api_key'], str)
			or not config['api_key']
		):
			raise ValueError('Model config lacks a model or API key.')
		self.model = config['model']
		self._key = config['api_key']
		self._http_client = DefaultAsyncHttpxClient(trust_env=False, follow_redirects=False)
		self._client = AsyncOpenAI(api_key=self._key, base_url=base_url, max_retries=0, timeout=40, http_client=self._http_client)
		self._usage_path = usage_path
		self._max_calls = max_calls
		self.calls = 0
		self.events: list[dict[str, Any]] = []

	@property
	def name(self) -> str:
		return self.model

	def _safe(self, value: Any) -> Any:
		text = json.dumps(value, ensure_ascii=False, default=str)
		text = text.replace(self._key, '[redacted model key]')
		text = re.sub(r'wss?://[^\\"\s]+', '[redacted CDP URL]', text)
		return json.loads(text)

	def _save(self) -> None:
		payload = self._safe(
			{
				'model': self.model,
				'calls_started': self.calls,
				'max_calls': self._max_calls,
				'max_tokens': 4096,
				'events': self.events,
				'cost': None,
				'currency': None,
			}
		)
		tmp = self._usage_path.with_suffix('.tmp')
		with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
			json.dump(payload, stream, ensure_ascii=False, indent=2)
			stream.flush()
			os.fsync(stream.fileno())
		os.replace(tmp, self._usage_path)

	async def ainvoke(self, messages, output_format=None, **kwargs):
		if self.calls >= self._max_calls:
			raise RuntimeError('Bounded model call budget exhausted.')
		formatted = OpenAIMessageSerializer.serialize_messages(messages)
		if output_format is not None:
			schema = SchemaOptimizer.create_optimized_json_schema(output_format)
			schema_text = (
				'\n<json_schema>\n' + json.dumps(schema) + '\n</json_schema>\nReturn one bare JSON object matching this schema.'
			)
			if formatted and formatted[0]['role'] == 'system' and isinstance(formatted[0]['content'], str):
				formatted[0]['content'] += schema_text
			else:
				formatted.insert(0, {'role': 'system', 'content': schema_text})
		event: dict[str, Any] = {
			'call_number': self.calls + 1,
			'structured': output_format is not None,
			'roles': [m['role'] for m in formatted],
			'message_sizes': [len(json.dumps(m, ensure_ascii=False, default=str)) for m in formatted],
		}
		self.calls += 1
		self.events.append(event)
		self._save()
		try:
			response = await self._client.chat.completions.create(
				model=self.model,
				messages=formatted,
				response_format={'type': 'json_object'} if output_format is not None else omit,
				max_tokens=4096,
				temperature=0,
			)
			choice = response.choices[0]
			usage = response.usage
			event.update(
				{
					'completion_id': response.id,
					'finish_reason': choice.finish_reason,
					'prompt_tokens': usage.prompt_tokens if usage else None,
					'completion_tokens': usage.completion_tokens if usage else None,
					'total_tokens': usage.total_tokens if usage else None,
				}
			)
			content = choice.message.content or ''
			if choice.finish_reason == 'length':
				raise RuntimeError('Model output hit the 4096-token cap.')
			parsed = output_format.model_validate_json(content) if output_format is not None else content
			event['schema_valid'] = True
			if output_format is not None and hasattr(parsed, 'action'):
				actions = [action.model_dump(exclude_none=True) for action in getattr(parsed, 'action')]
				event['parsed_actions'] = [list(action) for action in actions]
			return ChatInvokeCompletion(
				completion=parsed,
				usage=ChatInvokeUsage(
					prompt_tokens=usage.prompt_tokens,
					prompt_cached_tokens=None,
					prompt_cache_creation_tokens=None,
					prompt_image_tokens=None,
					completion_tokens=usage.completion_tokens,
					total_tokens=usage.total_tokens,
				)
				if usage
				else None,
				stop_reason=choice.finish_reason,
			)
		except Exception as error:
			event['error_type'] = type(error).__name__
			if 'finish_reason' in event and 'schema_valid' not in event:
				event['schema_valid'] = False
			raise
		finally:
			self._save()

	async def close(self) -> None:
		await self._client.close()
