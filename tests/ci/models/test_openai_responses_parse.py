"""Tests for shared OpenAI Responses parsing."""

import pytest
from openai.types.responses import Response
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.openai.responses import parse_responses_completion


class _TinyOutput(BaseModel):
	done: bool


def _response(*, status: str = 'completed', text: str = '{"done":true}') -> Response:
	payload = {
		'id': 'resp_test',
		'created_at': 1.0,
		'model': 'gpt-5.6',
		'object': 'response',
		'parallel_tool_calls': True,
		'tool_choice': 'auto',
		'tools': [],
		'status': status,
		'output': [],
		'usage': {
			'input_tokens': 4,
			'input_tokens_details': {'cached_tokens': 2},
			'output_tokens': 2,
			'output_tokens_details': {'reasoning_tokens': 0},
			'total_tokens': 6,
		},
	}
	if status == 'completed':
		payload['output'] = [
			{
				'id': 'msg_test', 'type': 'message', 'status': 'completed', 'role': 'assistant',
				'content': [{'type': 'output_text', 'text': text, 'annotations': [], 'logprobs': []}],
			}
		]
	return Response.model_validate(payload)


def test_parse_completed_structured_response_and_usage():
	result = parse_responses_completion(_response(), _TinyOutput, model='gpt-5.6', max_output_tokens=64)
	assert result.completion == _TinyOutput(done=True)
	assert result.usage is not None
	assert result.usage.prompt_cached_tokens == 2


def test_structured_response_rejects_trailing_junk():
	with pytest.raises(ModelProviderError):
		parse_responses_completion(
			_response(text='{"done":true} trailing'), _TinyOutput, model='gpt-5.6', max_output_tokens=64
		)


def test_non_completed_status_is_rejected():
	response = _response()
	response.status = 'cancelled'
	response.output = []
	with pytest.raises(ModelProviderError, match='unexpected status'):
		parse_responses_completion(response, None, model='gpt-5.6', max_output_tokens=64)
