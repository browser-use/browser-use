from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import AgentOutput, AgentStepInfo, MessageCompactionSettings
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.service import Tools


@pytest.mark.parametrize(
	'code',
	[
		r'JSON.parse("{\"path\":\"C:\\\\temp\\\\report.json\"}")',
		r'(() => /^C:\\temp\\files$/.test("C:\\temp\\files"))()',
		r'document.querySelector("[data-label=\"Save\"]")',
	],
	ids=['escaped-json', 'regex-backslashes', 'escaped-selector'],
)
async def test_evaluate_sends_valid_javascript_to_cdp_unchanged(code: str):
	runtime_evaluate = AsyncMock(return_value={'result': {'value': True}})
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=runtime_evaluate))),
		session_id='test-session',
	)
	browser_session = SimpleNamespace(
		cdp_client=cdp_session.cdp_client,
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)

	result = await Tools().evaluate(code=code, browser_session=browser_session)

	assert result.error is None
	assert result.long_term_memory is not None
	assert code in result.long_term_memory
	assert 'Result:\nTrue' in result.long_term_memory
	runtime_evaluate.assert_awaited_once_with(
		params={'expression': code, 'returnByValue': True, 'awaitPromise': True},
		session_id='test-session',
	)


@pytest.mark.parametrize(
	'runtime_result',
	[
		{'exceptionDetails': {'text': 'SyntaxError'}},
		{'result': {'wasThrown': True}},
		RuntimeError('CDP disconnected'),
	],
	ids=['exception-details', 'was-thrown', 'cdp-error'],
)
async def test_evaluate_failure_retains_original_javascript_in_long_term_memory(runtime_result):
	code = r'JSON.parse("{\"path\":\"C:\\\\temp\\\\report.json\"}")'
	if isinstance(runtime_result, Exception):
		runtime_evaluate = AsyncMock(side_effect=runtime_result)
	else:
		runtime_evaluate = AsyncMock(return_value=runtime_result)
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=runtime_evaluate))),
		session_id='test-session',
	)
	browser_session = SimpleNamespace(
		cdp_client=cdp_session.cdp_client,
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)

	result = await Tools().evaluate(code=code, browser_session=browser_session)

	assert result.error is not None
	assert result.long_term_memory is not None
	assert code in result.long_term_memory


async def test_evaluate_bounds_javascript_in_long_term_memory():
	code = f'const payload = "{"x" * 3000}";'
	runtime_evaluate = AsyncMock(return_value={'result': {'value': True}})
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=runtime_evaluate))),
		session_id='test-session',
	)
	browser_session = SimpleNamespace(
		cdp_client=cdp_session.cdp_client,
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)

	result = await Tools().evaluate(code=code, browser_session=browser_session)

	assert result.long_term_memory is not None
	assert code[:2000] in result.long_term_memory
	assert code not in result.long_term_memory
	assert f'original length: {len(code)} characters' in result.long_term_memory


async def test_evaluate_javascript_survives_model_history_and_compaction(tmp_path: Path):
	code = r'JSON.parse("{\"path\":\"C:\\\\temp\\\\report.json\"}")'
	runtime_evaluate = AsyncMock(return_value={'result': {'value': 'found'}})
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=runtime_evaluate))),
		session_id='test-session',
	)
	browser_session = SimpleNamespace(
		cdp_client=cdp_session.cdp_client,
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)
	action_result = await Tools().evaluate(code=code, browser_session=browser_session)

	message_manager = MessageManager(
		task='Inspect the page',
		system_message=SystemMessage(content='Test system message'),
		file_system=FileSystem(tmp_path),
	)
	browser_state = BrowserStateSummary(
		url='https://example.com',
		title='Example',
		tabs=[],
		dom_state=SerializedDOMState(_root=None, selector_map={}),
	)
	model_output = AgentOutput(
		evaluation_previous_goal='Need to inspect page data',
		memory='Running a JavaScript query',
		next_goal='Use the query result',
		action=[],
	)
	step_info = AgentStepInfo(step_number=1, max_steps=10)
	message_manager.create_state_messages(
		browser_state_summary=browser_state,
		model_output=model_output,
		result=[action_result],
		step_info=step_info,
		use_vision=False,
	)

	assert code in message_manager.get_messages()[-1].text

	class RecordingCompactionLLM:
		model = 'test-compaction-model'

		def __init__(self):
			self.input_text = ''

		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.input_text = messages[-1].text
			return ChatInvokeCompletion(completion=f'Prior JavaScript: {code}', usage=None)

	compaction_llm = RecordingCompactionLLM()
	compacted = await message_manager.maybe_compact_messages(
		llm=cast(BaseChatModel, compaction_llm),
		settings=MessageCompactionSettings(
			compact_every_n_steps=1,
			trigger_char_count=1,
			keep_last_items=0,
		),
		step_info=AgentStepInfo(step_number=2, max_steps=10),
	)

	assert compacted is True
	assert code in compaction_llm.input_text
	assert code in message_manager.agent_history_description

	message_manager.create_state_messages(
		browser_state_summary=browser_state,
		step_info=AgentStepInfo(step_number=2, max_steps=10),
		use_vision=False,
		skip_state_update=True,
	)
	assert code in message_manager.get_messages()[-1].text
