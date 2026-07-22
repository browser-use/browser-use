from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from browser_use import Agent
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import AgentOutput, AgentStepInfo, MessageManagerState
from browser_use.browser.views import BrowserStateSummary, PageInfo, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.views import ChatInvokeCompletion


def _browser_state() -> BrowserStateSummary:
	return BrowserStateSummary(
		url='https://example.test/current',
		title='Current page',
		tabs=[TabInfo(target_id='abcd1234', url='https://example.test/current', title='Current page')],
		page_info=PageInfo(
			viewport_width=1280,
			viewport_height=720,
			page_width=1280,
			page_height=1440,
			scroll_x=0,
			scroll_y=0,
			pixels_above=0,
			pixels_below=720,
			pixels_left=0,
			pixels_right=0,
		),
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		is_pdf_viewer=False,
		recent_events=None,
		closed_popup_messages=[],
		screenshot=None,
	)


def _message_manager(tmp_path: Path, *, enabled: bool = True) -> MessageManager:
	return MessageManager(
		task='Complete the task',
		system_message=SystemMessage(content='Test system message'),
		file_system=FileSystem(base_dir=str(tmp_path), create_default_files=False),
		state=MessageManagerState(),
		include_native_thought_summaries=enabled,
	)


def _model_output(*, thought: str | None, memory: str) -> AgentOutput:
	return AgentOutput(thinking=thought, memory=memory, action=[])


def _state_text(message_manager: MessageManager) -> str:
	state_message = message_manager.state.history.state_message
	assert state_message is not None
	assert isinstance(state_message.content, str)
	return state_message.content


def _advance(message_manager: MessageManager, *, step: int, thought: str | None, memory: str) -> str:
	message_manager.create_state_messages(
		browser_state_summary=_browser_state(),
		model_output=_model_output(thought=thought, memory=memory),
		result=[],
		step_info=AgentStepInfo(step_number=step, max_steps=100),
		use_vision=False,
	)
	return _state_text(message_manager)


def test_complete_summaries_use_two_decision_window_outside_history(tmp_path: Path):
	message_manager = _message_manager(tmp_path)
	first = 'FIRST-' + 'a' * 5000
	second = 'SECOND-' + 'b' * 4000
	third = 'THIRD-' + 'c' * 3000

	first_prompt = _advance(message_manager, step=1, thought=first, memory='durable-one')
	assert f'<thought_summary steps_ago="1">\n{first}\n</thought_summary>' in first_prompt
	assert first not in message_manager.agent_history_description
	assert 'durable-one' in message_manager.agent_history_description

	second_prompt = _advance(message_manager, step=2, thought=second, memory='durable-two')
	assert f'<thought_summary steps_ago="2">\n{first}\n</thought_summary>' in second_prompt
	assert f'<thought_summary steps_ago="1">\n{second}\n</thought_summary>' in second_prompt

	third_prompt = _advance(message_manager, step=3, thought=third, memory='durable-three')
	assert first not in third_prompt
	assert f'<thought_summary steps_ago="2">\n{second}\n</thought_summary>' in third_prompt
	assert f'<thought_summary steps_ago="1">\n{third}\n</thought_summary>' in third_prompt
	assert second not in message_manager.agent_history_description
	assert third not in message_manager.agent_history_description
	assert all(memory in message_manager.agent_history_description for memory in ('durable-one', 'durable-two', 'durable-three'))


def test_missing_summaries_age_previous_summary_out(tmp_path: Path):
	message_manager = _message_manager(tmp_path)

	_advance(message_manager, step=1, thought='useful previous thought', memory='one')
	second_prompt = _advance(message_manager, step=2, thought=None, memory='two')
	assert '<thought_summary steps_ago="2">\nuseful previous thought\n</thought_summary>' in second_prompt

	third_prompt = _advance(message_manager, step=3, thought=None, memory='three')
	assert '<recent_thought_summaries>' not in third_prompt


def test_summary_window_is_after_volatile_state_and_before_step_info(tmp_path: Path):
	first_manager = _message_manager(tmp_path)
	second_manager = _message_manager(tmp_path)
	first_prompt = _advance(first_manager, step=1, thought='first complete thought', memory='same-memory')
	second_prompt = _advance(second_manager, step=1, thought='second complete thought', memory='same-memory')

	marker = '<recent_thought_summaries>'
	assert first_prompt[: first_prompt.index(marker)] == second_prompt[: second_prompt.index(marker)]
	assert first_prompt.index('</browser_state>') < first_prompt.index(marker) < first_prompt.index('<step_info>')


def test_non_flash_message_manager_does_not_replay_structured_thinking(tmp_path: Path):
	message_manager = _message_manager(tmp_path, enabled=False)
	prompt = _advance(message_manager, step=1, thought='ordinary structured thinking', memory='durable')

	assert '<recent_thought_summaries>' not in prompt
	assert 'ordinary structured thinking' not in prompt
	assert message_manager.state.recent_thought_summaries == []


@pytest.mark.asyncio
async def test_agent_keeps_native_summary_separate_from_durable_memory():
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'gemini-3.5-flash-lite'
	llm.model_name = 'gemini-3.5-flash-lite'
	llm.name = 'gemini-3.5-flash-lite'
	llm.provider = 'google'
	llm._verified_api_keys = True

	async def invoke_with_native_thought(*args, **kwargs):
		output_format = kwargs.get('output_format') or args[1]
		completion = output_format.model_validate(
			{
				'memory': 'durable model-authored memory',
				'action': [{'done': {'text': 'finished', 'success': True}}],
			}
		)
		return ChatInvokeCompletion(
			completion=completion,
			thinking='complete provider-native thought summary',
			usage=None,
		)

	llm.ainvoke.side_effect = invoke_with_native_thought
	agent = Agent(task='Complete the task', llm=llm, flash_mode=True, directly_open_url=False)
	output = await agent.get_model_output([UserMessage(content='current state')])

	assert output.memory == 'durable model-authored memory'
	assert output.thinking == 'complete provider-native thought summary'
