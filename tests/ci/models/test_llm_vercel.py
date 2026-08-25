"""Test Vercel AI Gateway model behavior."""

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import BaseModel

from browser_use.llm.vercel.chat import ChatVercel


class StructuredOutput(BaseModel):
	value: str


class StringablePattern:
	def __init__(self, value: str):
		self.value = value

	def __str__(self) -> str:
		return self.value


@pytest.mark.parametrize(
	('reasoning_models', 'expect_reasoning'),
	[
		([''], False),
		(['gpt-5'], True),
		(cast(list[str], [StringablePattern('gpt-5')]), True),
	],
)
async def test_reasoning_model_patterns_ignore_empty_entries(monkeypatch, reasoning_models, expect_reasoning):
	"""Empty patterns are ignored while string-compatible values remain supported."""
	model = 'openai/gpt-5-mini' if expect_reasoning else 'openai/gpt-4o'
	chat = ChatVercel(model=model, api_key='test', reasoning_models=reasoning_models)
	captured = {}

	async def create(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(
			choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'), finish_reason='stop')],
			usage=None,
		)

	client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
	monkeypatch.setattr(chat, 'get_client', lambda: client)

	result = await chat.ainvoke(messages=[], output_format=StructuredOutput)

	assert result.completion == StructuredOutput(value='ok')
	assert ('response_format' not in captured) is expect_reasoning
