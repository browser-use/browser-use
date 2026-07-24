"""DeepSeek Thinking Mode × structured-output `tool_choice` regression tests.

DeepSeek V4 defaults to Thinking Mode, which rejects a forced/named `tool_choice`
(HTTP 400 "Thinking mode does not support this tool_choice"). ChatDeepSeek must:
  - force a named tool only when thinking is off,
  - fall back to `tool_choice='auto'` (and recover JSON from message content) when on,
  - surface the `thinking`/`reasoning_effort` knobs via the request body,
  - be importable from the package top level.

These use pytest-httpserver as a real OpenAI-compatible endpoint (no mocking of the
LLM client itself), capturing the outgoing request body to assert request shaping.
"""

import json

from pydantic import BaseModel
from werkzeug.wrappers import Request, Response

from browser_use.llm.messages import UserMessage


class AgentOutput(BaseModel):
	action: str


def _record(requests: list[dict]):
	"""Handler that records the request body and replies with a plain JSON completion."""

	def handler(request: Request) -> Response:
		requests.append(json.loads(request.get_data()))
		body = {
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'deepseek-test',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"action": "from_content"}'},
					'finish_reason': 'stop',
				}
			],
			'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
		}
		return Response(json.dumps(body), content_type='application/json')

	return handler


def _record_toolcall(requests: list[dict]):
	"""Handler that records the request and replies with a native tool call."""

	def handler(request: Request) -> Response:
		requests.append(json.loads(request.get_data()))
		body = {
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'deepseek-test',
			'choices': [
				{
					'index': 0,
					'message': {
						'role': 'assistant',
						'content': None,
						'reasoning_content': 'let me think...',
						'tool_calls': [
							{
								'id': 'call_1',
								'type': 'function',
								'function': {'name': 'AgentOutput', 'arguments': '{"action": "from_tool"}'},
							}
						],
					},
					'finish_reason': 'tool_calls',
				}
			],
			'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
		}
		return Response(json.dumps(body), content_type='application/json')

	return handler


async def test_v4_default_is_non_thinking_and_forces_named_tool(httpserver):
	"""deepseek-v4-flash defaults to non-thinking (drop-in for deprecated deepseek-chat):
	must pin thinking=disabled and force a named tool so structured output is reliable."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	requests: list[dict] = []
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_handler(_record_toolcall(requests))

	llm = ChatDeepSeek(model='deepseek-v4-flash', api_key='test-key', base_url=httpserver.url_for('/v1'))
	result = await llm.ainvoke([UserMessage(content='hi')], output_format=AgentOutput)

	sent = requests[0]
	assert sent['tool_choice'] == {'type': 'function', 'function': {'name': 'AgentOutput'}}
	# V4 server-defaults to thinking, so we must explicitly pin it off to keep forced tool_choice legal
	assert sent['thinking'] == {'type': 'disabled'}
	assert result.completion.action == 'from_tool'


async def test_default_model_is_v4_flash():
	"""The library default migrated off the deprecated deepseek-chat to deepseek-v4-flash."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	assert ChatDeepSeek().model == 'deepseek-v4-flash'


async def test_reasoner_alias_stays_thinking(httpserver):
	"""deepseek-reasoner is the thinking alias → auto tool_choice, no thinking override injected."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	requests: list[dict] = []
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_handler(_record(requests))

	llm = ChatDeepSeek(model='deepseek-reasoner', api_key='test-key', base_url=httpserver.url_for('/v1'))
	result = await llm.ainvoke([UserMessage(content='hi')], output_format=AgentOutput)

	sent = requests[0]
	assert sent['tool_choice'] == 'auto'
	assert 'thinking' not in sent
	# structured output recovered from message content when no tool call is returned
	assert result.completion.action == 'from_content'


async def test_v4_thinking_enabled_downgrades_named_tool(httpserver):
	"""Explicit thinking=enabled on V4 → downgrade forced tool_choice to auto + send thinking."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	requests: list[dict] = []
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_handler(_record(requests))

	llm = ChatDeepSeek(
		model='deepseek-v4-flash',
		api_key='test-key',
		base_url=httpserver.url_for('/v1'),
		thinking={'type': 'enabled'},
		reasoning_effort='high',
	)
	await llm.ainvoke([UserMessage(content='hi')], output_format=AgentOutput)

	sent = requests[0]
	assert sent['tool_choice'] == 'auto'
	assert sent['thinking'] == {'type': 'enabled'}
	assert sent['reasoning_effort'] == 'high'


async def test_thinking_disabled_forces_named_tool(httpserver):
	"""Explicit thinking=disabled → forced named tool_choice + thinking in request body."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	requests: list[dict] = []
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_handler(_record_toolcall(requests))

	llm = ChatDeepSeek(
		model='deepseek-v4-flash',
		api_key='test-key',
		base_url=httpserver.url_for('/v1'),
		thinking={'type': 'disabled'},
	)
	result = await llm.ainvoke([UserMessage(content='hi')], output_format=AgentOutput)

	sent = requests[0]
	assert sent['tool_choice'] == {'type': 'function', 'function': {'name': 'AgentOutput'}}
	assert sent['thinking'] == {'type': 'disabled'}
	assert result.completion.action == 'from_tool'
	# reasoning_content surfaced on the completion
	assert result.thinking == 'let me think...'


async def test_legacy_non_thinking_model_forces_named_tool(httpserver):
	"""Legacy deepseek-chat with no thinking config → non-thinking, force named tool, no injection."""
	from browser_use.llm.deepseek.chat import ChatDeepSeek

	requests: list[dict] = []
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_handler(_record_toolcall(requests))

	llm = ChatDeepSeek(model='deepseek-chat', api_key='test-key', base_url=httpserver.url_for('/v1'))
	result = await llm.ainvoke([UserMessage(content='hi')], output_format=AgentOutput)

	sent = requests[0]
	assert sent['tool_choice'] == {'type': 'function', 'function': {'name': 'AgentOutput'}}
	assert 'thinking' not in sent
	assert result.completion.action == 'from_tool'


def test_top_level_import():
	"""ChatDeepSeek must be importable from the package top level and from browser_use.llm."""
	from browser_use import ChatDeepSeek as TopLevel
	from browser_use.llm import ChatDeepSeek as LlmLevel

	assert TopLevel is LlmLevel
