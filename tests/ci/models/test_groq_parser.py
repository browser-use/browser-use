"""Regression tests for JSON recovery from Groq failed generations."""

import json

import httpx
import pytest
from groq import APIStatusError
from pydantic import BaseModel

from browser_use.llm.groq.parser import try_parse_groq_failed_generation


class ParsedAnswer(BaseModel):
	answer: str


@pytest.mark.parametrize('wrapper', ['{}', '```json\n{}\n```', '```\n{}\n```'])
@pytest.mark.parametrize('answer', ['plain text', 'Use ``` for code fences', '```python\nprint("hello")\n```'])
def test_failed_generation_preserves_code_fences_in_json_strings(wrapper: str, answer: str):
	content = wrapper.format(json.dumps({'answer': answer}))
	response = httpx.Response(400, request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions'))
	error = APIStatusError(
		'Failed to generate JSON',
		response=response,
		body={'error': {'failed_generation': content}},
	)

	assert try_parse_groq_failed_generation(error, ParsedAnswer) == ParsedAnswer(answer=answer)
