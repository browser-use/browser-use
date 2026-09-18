"""Bounded TypeSafe choice requests for the opt-in native Jev experiment."""

import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ChoiceQuestion(BaseModel):
	model_config = ConfigDict(extra='forbid')
	type: Literal['choice']
	criteria: dict[str, Any]
	instructions: str


class ChoiceAnswer(BaseModel):
	choice: str
	confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
	probabilities: dict[str, float]


class JevClient:
	"""One connection pool, no retries, and an append-only ledger including cancelled calls."""

	def __init__(self, *, log_path: str | None = None, api_key: str | None = None):
		self.api_key = api_key or os.environ.get('TYPESAFE_API_KEY')
		if not self.api_key:
			raise ValueError('TYPESAFE_API_KEY is required when jev_mode is enabled')
		self.model = 'jev-1.13.0'
		self.log_path = Path(log_path) if log_path else None
		self.calls: list[dict[str, Any]] = []
		self.events: list[dict[str, Any]] = []
		self._http: httpx.AsyncClient | None = None

	def record(self, event: dict[str, Any]) -> None:
		self.events.append(event)
		if self.log_path:
			self.log_path.parent.mkdir(parents=True, exist_ok=True)
			with self.log_path.open('a') as file:
				file.write(json.dumps(event, allow_nan=False) + '\n')

	async def ask(self, *, state: dict[str, Any], questions: dict[str, Any], purpose: str) -> dict[str, Any]:
		"""Return validated answers; failures raise so callers can retain the original BU path."""
		validated = {name: ChoiceQuestion.model_validate(question) for name, question in questions.items()}
		if not 1 <= len(validated) <= 32 or any(not question.criteria for question in validated.values()):
			raise ValueError('Jev requires 1-32 nonempty choice questions')
		payload = {'model': self.model, 'state': state, 'questions': {k: q.model_dump() for k, q in validated.items()}}
		body = json.dumps(payload, allow_nan=False)
		if len(body) > 120_000:
			raise ValueError('Jev input exceeds bounded context')
		if self._http is None:
			self._http = httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False)
		record: dict[str, Any] = {
			'id': len(self.calls) + 1,
			'purpose': purpose,
			'requested_model': self.model,
			'input_chars': len(body),
			'questions': len(questions),
			'cost_usd': None,
			'input_tokens': None,
			'error': None,
		}
		self.calls.append(record)
		self.record({'event': 'request_started', **record})
		started = time.perf_counter()
		try:
			async with asyncio.timeout(5):
				response = await self._http.post(
					'https://api.typesafe.ai/v1/systemone',
					content=body,
					headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
				)
				response.raise_for_status()
				data = response.json()
				record['returned_model'] = data.get('model')
				usage = data.get('usage') or {}
				tokens = usage.get('input_tokens')
				if type(tokens) is int and tokens >= 0:
					record['input_tokens'] = tokens
					record['cost_usd'] = tokens * 0.042 / 1_000_000
				answers = data.get('answers', {})
				if set(answers) != set(validated):
					raise ValueError('Jev returned an incomplete question set')
				for name, question in validated.items():
					answer = ChoiceAnswer.model_validate(answers[name])
					probs = answer.probabilities
					if (
						answer.choice not in question.criteria
						or set(probs) != set(question.criteria)
						or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values())
						or abs(sum(probs.values()) - 1) > 0.02
						or probs[answer.choice] < max(probs.values()) - 1e-6
					):
						raise ValueError('Jev returned an invalid choice distribution')
					answers[name] = answer.model_dump()
				record['answers'] = answers
				return answers
		except BaseException as exc:
			record['error'] = type(exc).__name__
			raise
		finally:
			record['duration_seconds'] = time.perf_counter() - started
			self.record({'event': 'request_finished', **record})

	def summary(self) -> dict[str, Any]:
		return {
			'calls': len(self.calls),
			'known_cost_usd': sum(c['cost_usd'] or 0 for c in self.calls),
			'unknown_cost_calls': sum(c['cost_usd'] is None for c in self.calls),
			'input_tokens': sum(c['input_tokens'] or 0 for c in self.calls),
			'request_seconds': sum(c.get('duration_seconds', 0) for c in self.calls),
			'requested_model': self.model,
			'returned_models': sorted({c['returned_model'] for c in self.calls if c.get('returned_model')}),
		}

	async def close(self) -> None:
		if self._http is not None:
			await self._http.aclose()
