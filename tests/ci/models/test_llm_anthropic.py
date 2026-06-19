"""Test Anthropic model button click."""

from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.messages import UserMessage
from tests.ci.models.model_test_helper import run_model_button_click_test


class _WriteFileParams(BaseModel):
	file_name: str
	content: str


class _WriteFileAction(BaseModel):
	model_config = ConfigDict(extra='forbid')

	write_file: _WriteFileParams


class _AgentOutput(BaseModel):
	evaluation_previous_goal: str | None = None
	memory: str | None = None
	next_goal: str | None = None
	action: list[_WriteFileAction]


def _fake_usage() -> SimpleNamespace:
	return SimpleNamespace(
		input_tokens=1,
		output_tokens=1,
		cache_read_input_tokens=0,
		cache_creation_input_tokens=0,
		cache_creation=None,
	)


def _fake_response(content: list[SimpleNamespace]) -> SimpleNamespace:
	return SimpleNamespace(content=content, usage=_fake_usage(), stop_reason='end_turn')


async def test_anthropic_claude_sonnet_4_0(httpserver):
	"""Test Anthropic claude-sonnet-4-0 can click a button."""
	await run_model_button_click_test(
		model_class=ChatAnthropic,
		model_name='claude-sonnet-4-0',
		api_key_env='ANTHROPIC_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


async def test_anthropic_parses_minimax_text_invoke(monkeypatch):
	chat = ChatAnthropic(model='MiniMax-M3', api_key='test', base_url='https://api.minimax.io/anthropic')
	text = (
		']<]minimax[>[<tool_call>]<]minimax[>[<invoke name=write_file>]'
		'<parameter name=file_name>checklist.md</parameter>'
		'<parameter name=content>item one</parameter>'
		'</invoke></tool_call>'
	)

	async def fake_create_message(**_):
		return _fake_response([SimpleNamespace(type='text', text=text)])

	monkeypatch.setattr(chat, '_create_message', fake_create_message)
	response = await chat.ainvoke([UserMessage(content='write the checklist')], output_format=_AgentOutput)

	action = response.completion.action[0].write_file
	assert action.file_name == 'checklist.md'
	assert action.content == 'item one'


async def test_anthropic_wraps_flat_minimax_tool_input(monkeypatch):
	chat = ChatAnthropic(model='MiniMax-M3', api_key='test', base_url='https://api.minimax.io/anthropic')
	tool_input = {
		'evaluation_previous_goal': 'Opened the app',
		'memory': 'Need to create a checklist',
		'next_goal': 'Write the checklist file',
		'file_name': 'checklist.md',
		'content': 'item one',
	}

	async def fake_create_message(**_):
		return _fake_response([SimpleNamespace(type='tool_use', input=tool_input)])

	monkeypatch.setattr(chat, '_create_message', fake_create_message)
	response = await chat.ainvoke([UserMessage(content='write the checklist')], output_format=_AgentOutput)

	assert response.completion.memory == 'Need to create a checklist'
	action = response.completion.action[0].write_file
	assert action.file_name == 'checklist.md'
	assert action.content == 'item one'
