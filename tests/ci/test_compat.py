"""0.x API compatibility: what is kept, what raises (before any browser or billing starts). No browser needed."""

import pytest
from conftest import script
from pydantic import BaseModel

from browser_use import ActionResult, Agent, AgentHistoryList, Browser, Controller, Tools
from browser_use.agent.loop import Session, build_agent, run
from browser_use.repl import Repl


@pytest.fixture
def no_browser(monkeypatch):
	async def fail(self):
		raise AssertionError('browser started')

	monkeypatch.setattr(Browser, 'start', fail)


@pytest.mark.parametrize('kwarg', ['use_vision', 'max_actions_per_step', 'flash_mode', 'initial_actions', 'some_new_kwarg'])
def test_unsupported_0x_agent_kwarg_raises_naming_it(kwarg, no_browser):
	with pytest.raises(TypeError, match=rf'Agent\({kwarg}=\.\.\.\) is not supported in browser-use 1.0'):
		Agent('t', script()[0], **{kwarg: True})


async def test_unsupported_run_kwarg_raises(no_browser):
	agent = Agent('t', script()[0], browser=Browser(local=True))
	with pytest.raises(TypeError, match='on_step_start'):
		await agent.run(on_step_start=lambda a: None)


def test_domain_scoped_sensitive_data_raises(no_browser):
	with pytest.raises(TypeError, match='Domain-scoped'):
		Agent('t', script()[0], sensitive_data={'https://example.com': {'pw': 'x'}})


def test_removed_classes_raise_with_pointer():
	import browser_use

	for name in ['BrowserSession', 'BrowserProfile', 'ChatGroq', 'DomService']:
		with pytest.raises(ImportError, match='removed in browser-use 1.0'):
			getattr(browser_use, name)


def test_browser_session_alias_and_controller_alias():
	browser = Browser(local=True)
	assert Agent('t', script()[0], browser_session=browser).browser is browser
	assert Controller is Tools


def result(status='completed', output='done', error=None):
	return AgentHistoryList(status, str(output), output, 3, 1.5, {}, None, None, error, [])


def test_result_keeps_common_0x_methods():
	r = result()
	assert (r.final_result(), r.is_done(), r.is_successful(), r.errors(), r.has_errors()) == ('done', True, True, [], False)
	assert (r.total_duration_seconds(), r.number_of_steps(), r.structured_output) == (1.5, 3, None)
	failed = result('error', '', 'boom')
	assert (failed.final_result(), failed.is_done(), failed.is_successful(), failed.errors()) == (None, False, None, ['boom'])


@pytest.mark.parametrize('name', ['urls', 'screenshots', 'action_names', 'model_thoughts', 'history'])
def test_removed_result_methods_raise_not_implemented(name):
	with pytest.raises(NotImplementedError, match='MIGRATING.md'):
		getattr(result(), name)
	with pytest.raises(AttributeError):
		result().definitely_not_a_method


def test_tools_plain_function_and_param_model():
	tools = Tools()

	@tools.action('Price of a product')
	def get_price(sku: str) -> str:
		return f'{sku}: 9.99'

	class Order(BaseModel):
		sku: str
		qty: int

	@tools.registry.action('Place an order', param_model=Order)
	async def place_order(params):
		return ActionResult(extracted_content=f'{params.qty}x {params.sku}')

	assert [t.name for t in tools.functions] == ['get_price', 'place_order']
	assert get_price('a') == 'a: 9.99'  # the decorator returns the function unchanged


@pytest.mark.parametrize('param', ['browser_session', 'page_extraction_llm', 'file_system'])
def test_tools_injected_params_raise(param):
	tools = Tools()
	with pytest.raises(TypeError, match=param):
		exec(f'@tools.action("x")\nasync def act(text: str, {param}=None): pass', {'tools': tools})


def test_tools_domain_filters_and_reserved_names_raise():
	tools = Tools()
	with pytest.raises(TypeError, match='domains'):
		tools.action('x', domains=['*.example.com'])
	with pytest.raises(ValueError, match='built-in'):

		@tools.action('x')
		def finish(result: str):
			return result


async def test_custom_action_is_a_model_tool(tmp_path):
	tools = Tools()

	@tools.action('Price of a product')
	def get_price(sku: str) -> ActionResult:
		return ActionResult(extracted_content=f'{sku} costs 9.99')

	model, seen = script(('get_price', {'sku': 'A1'}), ('finish', {'result': 'done'}))
	session = Session(repl=Repl(tmp_path))
	r = await run(build_agent(model, tools=tools.functions), 'task', session, 'm')
	assert r.output == 'done'
	assert 'A1 costs 9.99' in str(seen[1][-1])


async def test_telemetry_event_has_no_code_or_secrets(tmp_path, monkeypatch):
	import browser_use.telemetry.service as service

	events = []

	class FakeTelemetry:
		def capture(self, event):
			events.append(event)

		def flush(self):
			pass

	monkeypatch.setattr(service, 'ProductTelemetry', FakeTelemetry)
	import browser_use.telemetry as telemetry

	monkeypatch.setattr(telemetry, 'ProductTelemetry', FakeTelemetry, raising=False)
	model, _ = script(('python', {'code': 'print("secret code cell")'}), ('finish', {'result': 'the answer'}))
	browser = Browser(local=True)

	async def no_start():
		return {}

	monkeypatch.setattr(browser, 'start', no_start)
	agent = Agent('log in with pw-123', model, browser=browser, sensitive_data={'pw': 'pw-123'}, workspace=tmp_path)
	await agent.run()
	(event,) = events
	props = event.properties
	assert props['agent_type'] == 'pydantic' and props['task'] == 'log in with <secret:pw>'
	assert props['action_history'] is None and props['urls_visited'] is None and props['final_result_response'] is None
	assert props['steps'] == 2 and props['success'] is True and props['judge_verdict'] is None
	assert 'secret code cell' not in str(props) and 'the answer' not in str(props)


@pytest.fixture
def fake_browser(monkeypatch):
	"""Browser.start/stop as no-ops that count stops; the REPL worker still runs for real."""
	stops = []

	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		stops.append(self)
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	return stops


def test_run_sync_follow_up_keeps_the_repl_with_keep_alive(fake_browser, tmp_path):
	# 0.x scripts call run_sync() twice; the REPL worker belongs to the first call's event loop.
	model, _ = script(
		('python', {'code': 'x = 41'}), ('finish', {'result': 'one'}), ('finish_from_repl', {'expression': 'str(x + 1)'})
	)
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	agent.add_new_task('again')
	second = agent.run_sync()
	assert second.final_result() == '42', second.error  # same REPL: the variable survived
	import asyncio

	asyncio.run(agent.close())  # from another loop: kills the worker without awaiting it
	assert agent._repl is None and not fake_browser


async def test_failed_follow_up_still_stops_the_browser(fake_browser, monkeypatch, tmp_path):
	model, _ = script(('finish', {'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True), workspace=tmp_path)
	assert (await agent.run()).final_result() == 'one' and len(fake_browser) == 1

	async def broken(self):
		raise RuntimeError('browser failed')

	monkeypatch.setattr(Browser, 'start', broken)
	agent.add_new_task('again')
	with pytest.raises(RuntimeError, match='browser failed'):
		await agent.run()
	assert len(fake_browser) == 2  # a pending follow-up no longer keeps a failed run's browser alive
