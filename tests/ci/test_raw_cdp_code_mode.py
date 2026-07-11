import json
from types import SimpleNamespace
from typing import Any

import pytest

from browser_use import Agent
from browser_use.agent.prompts import SystemPrompt
from browser_use.browser.views import TabInfo
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import UserMessage
from browser_use.tools.code_executor import CodeExecutionResult, InProcessPythonExecutor
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


class _FakeCdpClient:
	def __init__(self) -> None:
		self.calls: list[dict[str, Any]] = []
		self._event_registry = _FakeEventRegistry()

	async def send_raw(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
		call = {'method': method, 'params': params or {}, 'session_id': session_id}
		self.calls.append(call)
		if method == 'Runtime.evaluate' and '.innerText.strip()' in call['params'].get('expression', ''):
			description = 'TypeError: el.innerText.strip is not a function\n    at <anonymous>:2:18'
			return {
				'result': {'type': 'object', 'subtype': 'error', 'className': 'TypeError', 'description': description},
				'exceptionDetails': {
					'text': 'Uncaught',
					'lineNumber': 2,
					'columnNumber': 17,
					'exception': {'className': 'TypeError', 'description': description},
					'stackTrace': {
						'callFrames': [
							{'functionName': '', 'url': 'https://example.com/app.js', 'lineNumber': 2, 'columnNumber': 17}
						]
					},
				},
			}
		if method == 'Runtime.evaluate' and call['params'].get('expression') == '1 + 1':
			return {'result': {'value': 2}}
		if method == 'Runtime.evaluate' and call['params'].get('expression') == '() => [1, 2, 3]':
			return {'result': {'type': 'function', 'objectId': 'function-1', 'value': {}}}
		if method == 'Runtime.evaluate' and call['params'].get('expression') == '() => [4, 5, 6]':
			return {'result': {'type': 'function', 'value': {}}}
		if method == 'Runtime.evaluate' and '[4, 5, 6]' in call['params'].get('expression', ''):
			return {'result': {'type': 'object', 'value': [4, 5, 6]}}
		if method == 'Runtime.callFunctionOn' and call['params'].get('objectId') == 'function-1':
			return {'result': {'type': 'object', 'value': [1, 2, 3]}}
		return {'ok': True, **call}


class _FakeEventRegistry:
	def __init__(self) -> None:
		self._handlers: dict[str, Any] = {}

	def register(self, method: str, callback: Any) -> None:
		self._handlers[method] = callback

	def unregister(self, method: str) -> None:
		self._handlers.pop(method, None)


class _FakeBrowserSession:
	def __init__(self) -> None:
		self.cdp_client = _FakeCdpClient()
		self.session_manager: Any = None
		self.agent_focus_target_id = 'target-0001'

	async def get_or_create_cdp_session(self, target_id: str | None = None, focus: bool = True):
		return SimpleNamespace(session_id='page-session', target_id=target_id or self.agent_focus_target_id)

	async def get_tabs(self) -> list[TabInfo]:
		return [TabInfo(target_id='target-0001', url='https://example.com', title='Example')]

	async def get_target_id_from_tab_id(self, tab_id: str) -> str:
		raise ValueError(f'No target for {tab_id}')


class _FakeSessionManager:
	def __init__(self) -> None:
		self.session = SimpleNamespace(session_id='explicit-session')

	def get_session(self, session_id: str):
		return self.session if session_id == 'explicit-session' else None

	def get_all_sessions(self) -> dict[str, Any]:
		return {'explicit-session': self.session}

	def get_all_target_ids(self) -> list[str]:
		return ['target-0002']


class _FakeCodeExecutor:
	async def run(self, code: str) -> CodeExecutionResult:
		return CodeExecutionResult(output=f'ran: {code}', images=[{'name': 'chart.png', 'data': 'abc123'}])


@pytest.mark.asyncio
async def test_in_process_executor_uses_fresh_namespaces_and_routes_cdp():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]

	first = await executor.run('x = 40\nprint("hello")\nx + 2')
	assert first.error is None
	assert 'hello' in first.output
	assert '42' in first.output

	second = await executor.run('await cdp("Runtime.evaluate", {"expression": "x + 1"})')
	assert second.error is None
	assert '"method": "Runtime.evaluate"' in second.output
	assert browser_session.cdp_client.calls[-1] == {
		'method': 'Runtime.evaluate',
		'params': {'expression': 'x + 1'},
		'session_id': 'page-session',
	}
	assert (await executor.run('print("x" in globals())')).output.strip() == 'False'

	third = await executor.run('await cdp("Browser.getVersion")')
	assert third.error is None
	assert browser_session.cdp_client.calls[-1]['session_id'] is None


@pytest.mark.asyncio
async def test_in_process_executor_js_helper_returns_value():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]

	result = await executor.run('print(await js("1 + 1"))')

	assert result.error is None
	assert '2' in result.output
	assert browser_session.cdp_client.calls[-1] == {
		'method': 'Runtime.evaluate',
		'params': {'expression': '1 + 1', 'awaitPromise': True, 'returnByValue': True, 'timeout': 15000.0},
		'session_id': 'page-session',
	}


@pytest.mark.asyncio
async def test_evaluate_and_python_js_share_multiline_transport_and_detailed_errors():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]
	tools = Tools()
	ActionModel = tools.registry.create_action_model(include_actions=['evaluate'])
	multiline_javascript = """() => {
	const links = [...document.querySelectorAll('a')];
	return links.map(a => ({text: a.innerText, href: a.href, quote: `say "hello"`}));
}"""

	action = ActionModel.model_validate({'evaluate': {'code': multiline_javascript}})
	evaluate_result = await tools.act(action=action, browser_session=browser_session)  # type: ignore[arg-type]

	assert evaluate_result.error is None
	assert browser_session.cdp_client.calls[-1]['params']['expression'] == multiline_javascript

	failing_javascript = """() => {
	const el = document.body;
	return el.innerText.strip();
}"""
	python_result = await executor.run(f'await js({failing_javascript!r})')
	assert 'TypeError at line 3, column 18: el.innerText.strip is not a function' in (python_result.error or '')
	assert 'RuntimeError: Uncaught' not in (python_result.error or '')

	failing_action = ActionModel.model_validate({'evaluate': {'code': failing_javascript}})
	evaluate_error = await tools.act(action=failing_action, browser_session=browser_session)  # type: ignore[arg-type]
	assert evaluate_error.error == 'TypeError: el.innerText.strip is not a function'
	assert evaluate_error.extracted_content is not None
	assert 'line 3, column 18' in evaluate_error.extracted_content
	assert 'https://example.com/app.js' in evaluate_error.extracted_content


@pytest.mark.asyncio
async def test_in_process_executor_routes_arbitrary_cdp_to_explicit_session_or_target():
	browser_session = _FakeBrowserSession()
	browser_session.session_manager = _FakeSessionManager()

	async def get_target_session(target_id: str | None = None, focus: bool = True):
		return SimpleNamespace(session_id=f'session-for-{target_id or "focused"}', target_id=target_id)

	browser_session.get_or_create_cdp_session = get_target_session  # type: ignore[method-assign]
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]

	result = await executor.run(
		'await cdp("Fetch.enable", {"patterns": []}, session="explicit-session")\n'
		'await cdp("Storage.getCookies", session="target-0002")\n'
		'await cdp("Target.getTargets", session="root")'
	)

	assert result.error is None
	assert [call['method'] for call in browser_session.cdp_client.calls] == [
		'Fetch.enable',
		'Storage.getCookies',
		'Target.getTargets',
	]
	assert [call['session_id'] for call in browser_session.cdp_client.calls] == [
		'explicit-session',
		'session-for-target-0002',
		None,
	]


@pytest.mark.asyncio
async def test_in_process_executor_bounds_individual_cdp_waits():
	browser_session = _FakeBrowserSession()

	async def never_returns(*args, **kwargs):
		await __import__('asyncio').sleep(10)

	browser_session.cdp_client.send_raw = never_returns  # type: ignore[method-assign]
	executor = InProcessPythonExecutor(browser_session=browser_session, timeout=2)  # type: ignore[arg-type]

	result = await executor.run('await cdp("Runtime.evaluate", {"expression": "1 + 1"}, request_timeout=0.1)')

	assert result.timed_out is False
	assert 'TimeoutError' in (result.error or '')
	assert result.duration_seconds < 1


@pytest.mark.asyncio
async def test_in_process_executor_js_helper_invokes_returned_function():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]

	result = await executor.run('print(await js("() => [1, 2, 3]"))')

	assert result.error is None
	assert '[1, 2, 3]' in result.output
	assert [call['method'] for call in browser_session.cdp_client.calls] == [
		'Runtime.evaluate',
		'Runtime.callFunctionOn',
	]


@pytest.mark.asyncio
async def test_in_process_executor_js_helper_reinvokes_function_without_object_id():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]

	result = await executor.run('print(await js("() => [4, 5, 6]"))')

	assert result.error is None
	assert '[4, 5, 6]' in result.output
	assert [call['method'] for call in browser_session.cdp_client.calls] == [
		'Runtime.evaluate',
		'Runtime.evaluate',
	]


@pytest.mark.asyncio
async def test_in_process_executor_waits_for_events_without_clobbering_existing_handler():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session)  # type: ignore[arg-type]
	original_events: list[dict[str, Any]] = []

	async def original_handler(params: dict[str, Any], session_id: str | None) -> None:
		original_events.append({'params': params, 'session_id': session_id})

	registry = browser_session.cdp_client._event_registry
	registry.register('Network.responseReceived', original_handler)
	run_task = __import__('asyncio').create_task(
		executor.run('event = await wait_for_event("Network.responseReceived", timeout=2)\nprint(event["response"]["url"])')
	)
	for _ in range(100):
		handler = registry._handlers.get('Network.responseReceived')
		if handler is not None and handler is not original_handler:
			break
		await __import__('asyncio').sleep(0.01)
	else:
		pytest.fail('Raw CDP event waiter was not registered.')

	await handler({'response': {'url': 'https://example.com/data'}}, 'page-session')
	result = await run_task

	assert result.error is None
	assert result.output.strip() == 'https://example.com/data'
	assert original_events == [{'params': {'response': {'url': 'https://example.com/data'}}, 'session_id': 'page-session'}]
	assert registry._handlers['Network.responseReceived'] is original_handler


@pytest.mark.asyncio
async def test_in_process_executor_timeout_restores_event_handler():
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session, timeout=0.25)  # type: ignore[arg-type]

	def original_handler(params: dict[str, Any], session_id: str | None) -> None:
		pass

	registry = browser_session.cdp_client._event_registry
	registry.register('Network.loadingFinished', original_handler)
	result = await executor.run('await wait_for_event("Network.loadingFinished", timeout=30)')

	assert result.timed_out is True
	assert registry._handlers['Network.loadingFinished'] is original_handler


@pytest.mark.asyncio
async def test_in_process_executor_writes_workspace_files(tmp_path):
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(browser_session=browser_session, workspace_dir=tmp_path)  # type: ignore[arg-type]

	result = await executor.run(
		'path = WORKSPACE_DIR / "report.md"\npath.write_text("hello")\nprint(path.resolve())\nprint(path.read_text())\nprint(WORKSPACE_DIR)'
	)

	assert result.error is None
	assert (tmp_path / 'report.md').read_text() == 'hello'
	assert str(tmp_path / 'report.md') in result.output
	assert 'hello' in result.output
	assert str(tmp_path) in result.output

	plain_open = await executor.run('with open("plain.csv", "w") as f:\n    _ = f.write("a,b")\nprint(open("plain.csv").read())')
	assert plain_open.error is None
	assert (tmp_path / 'plain.csv').read_text() == 'a,b'
	assert 'a,b' in plain_open.output

	nested = await executor.run(
		'path = WORKSPACE_DIR / "nested/report.md"\npath.parent.mkdir(parents=True, exist_ok=True)\npath.write_text("good")'
	)
	assert nested.error is None
	assert (tmp_path / 'nested' / 'report.md').read_text() == 'good'


@pytest.mark.asyncio
async def test_in_process_executor_workspace_files_are_visible_to_read_file(tmp_path):
	browser_session = _FakeBrowserSession()
	file_system = FileSystem(tmp_path)
	executor = InProcessPythonExecutor(browser_session=browser_session, file_system=file_system)  # type: ignore[arg-type]

	result = await executor.run(
		'path = WORKSPACE_DIR / "quotes.json"\npath.write_text("{\\"ok\\": true}")\nprint(path.resolve())'
	)

	assert result.error is None
	assert str(file_system.get_dir() / 'quotes.json') in result.output
	assert await file_system.read_file('quotes.json') == 'Read from file quotes.json.\n<content>\n{"ok": true}\n</content>'
	assert (file_system.get_dir() / 'quotes.json').read_text() == '{"ok": true}'


@pytest.mark.asyncio
async def test_in_process_executor_cooperatively_times_out_and_recovers(tmp_path):
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(
		browser_session=browser_session,  # type: ignore[arg-type]
		workspace_dir=tmp_path,
		timeout=0.25,
	)

	result = await executor.run('await asyncio.sleep(10)')
	assert result.timed_out is True
	assert 'Cooperative cancellation was requested' in (result.error or '')
	assert (await executor.run('print("still works")')).output.strip() == 'still works'


@pytest.mark.asyncio
async def test_in_process_executor_never_leaves_cancellation_resistant_code_running(tmp_path):
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(
		browser_session=browser_session,  # type: ignore[arg-type]
		workspace_dir=tmp_path,
		timeout=0.05,
	)

	result = await executor.run(
		'try:\n'
		'    await asyncio.sleep(10)\n'
		'except asyncio.CancelledError:\n'
		'    await asyncio.sleep(0.1)\n'
		'    print("cleanup finished")'
	)

	assert result.timed_out is True
	assert result.duration_seconds >= 0.1
	assert result.output.strip() == 'cleanup finished'


@pytest.mark.asyncio
async def test_in_process_executor_bounds_output(tmp_path):
	browser_session = _FakeBrowserSession()
	executor = InProcessPythonExecutor(
		browser_session=browser_session,  # type: ignore[arg-type]
		workspace_dir=tmp_path,
		max_output_chars=100,
	)

	result = await executor.run('print("x" * 1000)')
	assert result.error is None
	assert 'characters omitted' in result.output
	assert len(result.output) < 200


@pytest.mark.asyncio
async def test_file_reads_are_bounded_and_continuable(tmp_path):
	file_system = FileSystem(tmp_path, create_default_files=False)
	path = file_system.get_dir() / 'large.json'
	path.write_text('x' * 20_000)

	first = await file_system.read_file('large.json', max_chars=1000)
	assert len(first) < 1200
	assert 'Continue with offset=1000' in first
	second = await file_system.read_file('large.json', offset=1000, max_chars=1000)
	assert 'Read bytes 1000-2000 of 20000' in second


def test_workspace_listing_and_search_use_canonical_root(tmp_path):
	real_root = tmp_path / 'real-root'
	real_root.mkdir()
	alias_root = tmp_path / 'alias-root'
	alias_root.symlink_to(real_root, target_is_directory=True)
	file_system = FileSystem(alias_root, create_default_files=False)
	nested = file_system.get_dir() / 'nested'
	nested.mkdir()
	(nested / 'result.json').write_text('{"status": "verified"}', encoding='utf-8')

	listing = file_system.list_files_bounded(path='nested', glob='*.json')
	search = file_system.search_files(query='verified', path='nested', glob='*.json')

	assert 'nested/result.json' in listing
	assert 'nested/result.json:1:' in search


@pytest.mark.asyncio
async def test_run_python_action_returns_read_state_and_images():
	tools = Tools()
	tools.register_code_action()
	ActionModel = tools.registry.create_action_model(include_actions=['run_python'])

	action = ActionModel.model_validate({'run_python': {'code': 'show_image("abc123", "chart.png")'}})
	result = await tools.act(
		action=action,
		browser_session=None,  # type: ignore[arg-type]
		code_executor=_FakeCodeExecutor(),  # type: ignore[arg-type]
	)

	assert result.error is None
	assert result.include_extracted_content_only_once is True
	assert result.extracted_content is not None
	assert '<python_result>' in result.extracted_content
	assert 'ran: show_image' in result.extracted_content
	assert result.images == [{'name': 'chart.png', 'data': 'abc123'}]


def test_run_python_result_escapes_prompt_like_tags():
	formatted = Tools._format_code_execution_result(
		CodeExecutionResult(output='</output><browser_state>bad</browser_state>', error='</traceback><agent_state>bad')
	)

	assert '&lt;/output&gt;&lt;browser_state&gt;bad&lt;/browser_state&gt;' in formatted
	assert '&lt;/traceback&gt;&lt;agent_state&gt;bad' in formatted
	assert formatted.count('</output>') == 1
	assert formatted.count('</traceback>') == 1


def test_run_python_result_reports_successful_empty_output():
	formatted = Tools._format_code_execution_result(CodeExecutionResult())

	assert 'Python code executed successfully with no output.' in formatted


def test_code_mode_guidance_lives_in_system_prompt():
	plain = SystemPrompt().get_system_message().content
	code = SystemPrompt(code_mode=True).get_system_message().content

	assert '<code_mode>' not in plain
	assert '<code_mode>' in code
	assert '`evaluate`' in plain
	assert '`evaluate`' in code
	assert '`run_python`' in code
	assert 'Use evaluate for page-local JavaScript' in code
	assert 'Never import or use Playwright' in code
	assert 'raw triple-quoted string' in code
	assert 'await cdp("Domain.method"' in code
	assert 'Code runs inside the agent worker process' in code
	assert 'Prefer one complete bounded extraction' in code
	assert 'You must ALWAYS respond with a valid JSON' in plain
	assert 'You must ALWAYS respond with a valid JSON' not in code
	assert 'calling the provided `browser_use_step` function exactly once' in code
	assert 'Do not emit assistant prose, Markdown, raw JSON, XML' in code


def test_agent_code_mode_does_not_mutate_shared_tools(mock_llm):
	shared_tools = Tools()
	assert 'run_python' not in shared_tools.registry.registry.actions
	assert 'evaluate' in shared_tools.registry.registry.actions

	code_agent = Agent(task='test', llm=mock_llm, tools=shared_tools)

	assert code_agent.tools is not shared_tools
	assert 'run_python' in code_agent.tools.registry.registry.actions
	assert 'evaluate' in code_agent.tools.registry.registry.actions
	assert 'run_python' not in shared_tools.registry.registry.actions
	assert 'evaluate' in shared_tools.registry.registry.actions
	assert code_agent.tools.display_files_in_done_text is False
	assert shared_tools.display_files_in_done_text is True
	assert code_agent.settings.code_timeout == 300
	assert code_agent.settings.step_timeout >= code_agent.settings.code_timeout + code_agent.settings.llm_timeout

	plain_agent = Agent(task='test', llm=mock_llm, tools=shared_tools, code=False)
	assert plain_agent.tools is shared_tools
	assert 'run_python' not in plain_agent.tools.registry.registry.actions
	assert 'evaluate' in plain_agent.tools.registry.registry.actions
	assert plain_agent.tools.display_files_in_done_text is True

	explicit_preview_agent = Agent(task='test', llm=mock_llm, tools=shared_tools, code=True, display_files_in_done_text=True)
	assert explicit_preview_agent.tools.display_files_in_done_text is True


def test_code_mode_does_not_treat_cdp_method_as_url(mock_llm):
	agent = Agent(task='Call await cdp("Browser.getVersion") once.', llm=mock_llm, code=True)
	assert agent.initial_url is None


@pytest.mark.asyncio
async def test_agent_code_mode_requests_one_native_output_tool(mock_llm):
	agent = Agent(task='test', llm=mock_llm, code=True)

	result = await agent.get_model_output([UserMessage(content='act')])

	assert result.action[0].model_dump(exclude_none=True)['done']['success'] is True
	kwargs = mock_llm.last_invoke_kwargs
	assert kwargs['tool_choice'] == 'required'
	assert len(kwargs['tools']) == 1
	assert kwargs['tools'][0].name == 'browser_use_step'
	assert kwargs['tools'][0].parameters['required'] == ['step']
	assert 'run_python' in str(kwargs['tools'][0].parameters)
	assert 'evaluate' in str(kwargs['tools'][0].parameters)


@pytest.mark.asyncio
async def test_agent_run_executes_no_output_python_cell_in_process_and_continues(browser_session):
	llm = create_mock_llm(
		actions=[
			json.dumps(
				{
					'thinking': 'Use direct page JavaScript.',
					'evaluation_previous_goal': 'Starting.',
					'memory': 'Need to execute one cell.',
					'next_goal': 'Run JavaScript without printing.',
					'action': [{'run_python': {'code': 'value = await js("1 + 1")'}}],
				}
			)
		]
	)
	agent = Agent(
		task='Run one Python cell, then finish.',
		llm=llm,
		browser=browser_session,
		code=True,
		use_judge=False,
		enable_signal_handler=False,
	)

	history = await agent.run(max_steps=2)

	assert history.action_names() == ['run_python', 'done']
	assert history.is_done() is True
	assert history.final_result() == 'Task completed successfully'
	assert any(
		result.extracted_content and 'Python code executed successfully with no output.' in result.extracted_content
		for result in history.action_results()
	)
