"""0.x API compatibility: what is kept, what raises (before any browser or billing starts). No browser needed."""

import pytest
from conftest import script
from pydantic import BaseModel

from browser_use import ActionResult, Agent, AgentHistoryList, Browser, ChatAnthropic, ChatGoogle, Controller, Tools
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


def test_domain_scoped_sensitive_data_is_accepted_and_bad_shapes_raise(no_browser):
	Agent('t', script()[0], sensitive_data={'https://example.com': {'pw': 'x'}, 'pin': '1'})
	with pytest.raises(TypeError, match='must be a string'):
		Agent('t', script()[0], sensitive_data={'pw': 123})


def test_dotenv_in_the_working_directory_supplies_the_key(tmp_path):
	"""Roast C16: 0.x loaded .env on import; 1.0 resolved the key before anything read .env ('missing key')."""
	import os
	import subprocess
	import sys

	(tmp_path / '.env').write_text('BROWSER_USE_API_KEY=fake-dotenv-key\n', encoding='utf-8')
	env = {k: v for k, v in os.environ.items() if k != 'BROWSER_USE_API_KEY'}
	env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / 'cfg'))
	code = "from browser_use import Agent\nAgent('t')._build()\nprint('resolved')"
	r = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
	assert r.stdout.strip() == 'resolved', r.stderr[-2000:]


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


async def test_custom_tool_results_never_show_a_secret_to_the_model(tmp_path):
	"""Roast r2-1: a custom action returning a registered secret (ActionResult, nested model, plain str, retry
	message) reached the model in plaintext; 0.x filtered action results."""
	from pydantic_ai import ModelRetry

	secret = 'hunter2-Zq9'
	tools = Tools()

	class Account(BaseModel):
		user: str
		password: str

	@tools.action('Look up the account')
	def account() -> ActionResult:
		return ActionResult(extracted_content=f'pw={secret}', account=Account(user='me', password=secret))

	@tools.action('Read a note')
	def note() -> list:
		return [{'text': f'the password is {secret}'}]

	@tools.action('Check')
	def check() -> str:
		raise ModelRetry(f'wrong password {secret}')

	model, seen = script(('account', {}), ('note', {}), ('check', {}), ('finish', {'result': 'done'}))
	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(model, tools=tools.functions), 'task', session, 'm')
	assert r.output == 'done'
	assert secret not in str(seen) and secret not in str(r.messages)
	assert 'pw=<secret:pw>' in str(seen[1][-1]) and 'wrong password <secret:pw>' in str(seen[3][-1])


@pytest.mark.parametrize('tool', ['finish', 'finish_from_repl'])
async def test_finish_can_report_a_failed_task(tool, tmp_path):
	"""Roast C9: 'Unable to log in. Access denied.' came back with is_successful() == True; 0.x had success=False."""
	args = {'result': 'Unable to log in. Access denied.'} if tool == 'finish' else {'expression': "'Access denied.'"}
	model, _ = script((tool, {**args, 'success': False}))
	r = await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.is_done(), r.is_successful(), r.success) == (True, False, False)
	model, _ = script(('finish', {'result': 'done'}))
	assert (await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')).is_successful() is True


async def test_structured_final_result_is_the_models_json(tmp_path):
	"""Roast C10: final_result() was '"title=\'x\' points=3"' (str() of the model) instead of 0.x model_dump_json()."""

	class Story(BaseModel):
		title: str
		points: int

	model, _ = script(('finish', {'result': {'title': 'x', 'points': 3}}))
	r = await run(build_agent(model, output_type=Story), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert r.final_result() == Story(title='x', points=3).model_dump_json()
	assert r.structured_output == Story(title='x', points=3)


async def test_a_tools_own_timeout_is_an_error_not_the_run_budget(tmp_path):
	"""Fable: socket.timeout is TimeoutError; it was reported as status='timeout', error=None with budget unused."""
	tools = Tools()

	@tools.action('Fetch a URL')
	def fetch(url: str) -> str:
		raise TimeoutError('timed out')

	model, _ = script(('fetch', {'url': 'https://x.test'}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.status, r.error) == ('error', 'TimeoutError: timed out')


@pytest.mark.parametrize(
	'llm', [lambda: ChatAnthropic('claude-opus-4-1', api_key='k'), lambda: ChatGoogle('gemini-2.5-pro', api_key='k')]
)
async def test_cost_is_priced_with_the_models_provider(llm, fake_browser, tmp_path, monkeypatch):
	"""Fable: the bare model name was priced as OpenAI, so cost_usd was None for every Anthropic/Google model."""
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	import browser_use.agent.service as service
	from browser_use.agent.loop import usage_and_cost

	refs = []

	async def fake_run(agent, task, session, model_ref, **kw):
		refs.append(model_ref)
		return result()

	monkeypatch.setattr(service, 'run', fake_run)
	await Agent('t', llm(), browser=Browser(local=True), workspace=tmp_path).run()
	usage = RequestUsage(input_tokens=1000, output_tokens=100)
	assert usage_and_cost([ModelResponse(parts=[TextPart('x')], usage=usage)], refs[0])[1]


async def test_param_model_is_authoritative(tmp_path):
	"""Roast C14: with `params: Any` the param_model was ignored; the action got a dict and params.qty broke."""
	from typing import Any

	tools = Tools()

	class Order(BaseModel):
		sku: str
		qty: int

	@tools.action('Place an order', param_model=Order)
	def place_order(params: Any) -> str:
		return f'{params.qty}x {params.sku}'

	model, seen = script(('place_order', {'params': {'sku': 'A1', 'qty': '3'}}), ('finish', {'result': 'done'}))
	await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert '3x A1' in str(seen[1][-1])


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

	runner_loop = agent._runner.get_loop()
	asyncio.run(agent.close())  # from another loop: kills the worker without awaiting it
	assert agent._repl is None and not fake_browser
	assert agent._runner is None and runner_loop.is_closed()  # Fable r2-9: run_sync's loop leaked


def test_close_sync_ends_run_sync_follow_ups(fake_browser, tmp_path):
	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	runner_loop, repl = agent._runner.get_loop(), agent._repl
	agent.close_sync()
	assert agent._runner is None and runner_loop.is_closed() and agent._repl is None
	assert repl.proc is None


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


async def test_failed_follow_up_never_returns_the_previous_tasks_result(tmp_path):
	"""Roast r2-6: a follow-up that failed before its first checkpoint returned the previous task's partial or last
	text as its own result."""
	from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
	from pydantic_ai.models.function import FunctionModel

	def broken(messages, info):
		raise RuntimeError('provider down')

	history = [ModelRequest(parts=[UserPromptPart('task A')]), ModelResponse(parts=[TextPart('answer to task A')])]
	repl = Repl(tmp_path)
	repl.state.mkdir(parents=True)
	(repl.state / 'partial.json').write_text('{"file": "a.json", "value": "partial of task A"}', encoding='utf-8')
	r = await run(build_agent(FunctionModel(broken)), 'task B', Session(repl=repl), 'm', message_history=history)
	assert (r.status, r.partial, r.text) == ('error', None, '')


async def test_run_error_never_shows_a_secret(tmp_path):
	"""Roast r2-8: an exception quoting a registered secret stayed plaintext in result.error, which Agent.run logs."""
	secret = 'hunter2-Zq9'
	tools = Tools()

	@tools.action('Log in')
	def login() -> str:
		raise RuntimeError(f'login failed for password {secret}')

	model, _ = script(('login', {}))
	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(model, tools=tools.functions), 'task', session, 'm')
	assert r.status == 'error' and r.error == 'RuntimeError: login failed for password <secret:pw>'


def test_cost_includes_cache_writes():
	"""Roast r2-9: cache_write_tokens were dropped from pricing, so Anthropic runs were under-reported."""
	from genai_prices import Usage, calc_price
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	u = RequestUsage(input_tokens=6000, cache_write_tokens=5000, cache_read_tokens=0, output_tokens=500)
	usage, cost = usage_and_cost([ModelResponse(parts=[TextPart('x')], usage=u)], 'anthropic:claude-sonnet-4-5')
	expected = calc_price(
		Usage(input_tokens=6000, cache_write_tokens=5000, output_tokens=500), 'claude-sonnet-4-5', provider_id='anthropic'
	)
	assert cost == float(expected.total_price) and usage['cache_write'] == 5000


def test_action_result_imports_from_its_0x_location():
	"""Fable r2-7: `from browser_use.agent.views import ActionResult` (0.x's canonical import) raised ImportError."""
	from browser_use.agent.views import ActionResult as Old

	assert Old is ActionResult
