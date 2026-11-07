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


REMOVED = (
	r'was removed in browser-use 1\.0\. Open an issue at https://github\.com/browser-use/browser-use/issues if you need it\.'
)


@pytest.mark.parametrize(
	'kwarg',
	[
		'use_vision',  # vision tuning
		'vision_detail_level',
		'max_actions_per_step',
		'flash_mode',
		'initial_actions',
		'register_new_step_callback',  # step callbacks
		'register_done_callback',
		'register_should_stop_callback',
		'generate_gif',
		'use_judge',  # judge
		'judge_llm',
		'ground_truth',
		'enable_planning',  # planner
		'planner_llm',
		'planning_replan_on_stall',
	],
)
def test_removed_0x_agent_kwarg_raises_one_error_naming_it(kwarg, no_browser):
	with pytest.raises(TypeError, match=rf'^Agent\({kwarg}=\.\.\.\) {REMOVED}'):
		Agent('t', script()[0], **{kwarg: True})


def test_unknown_agent_kwarg_is_not_called_removed(no_browser):
	with pytest.raises(TypeError, match=r'^Agent\(some_new_kwarg=\.\.\.\) is not a browser-use 1\.0 option'):
		Agent('t', script()[0], some_new_kwarg=True)


def test_removed_alternative_is_named(no_browser):
	with pytest.raises(TypeError, match=r"In 1\.0: reasoning='low' \| 'medium' \| 'high'\.$"):
		Agent('t', script()[0], use_thinking=True)


async def test_step_hooks_on_run_raise(no_browser):
	agent = Agent('t', script()[0], browser=Browser(local=True))
	for hook in ('on_step_start', 'on_step_end'):
		with pytest.raises(TypeError, match=rf'^Agent\.run\({hook}=\.\.\.\) {REMOVED} In 1\.0: result\.messages'):
			await agent.run(**{hook: lambda a: None})
	with pytest.raises(TypeError, match=rf'^Agent\.run_sync\(on_step_end=\.\.\.\) {REMOVED}'):
		agent.run_sync(on_step_end=lambda a: None)


@pytest.mark.parametrize(
	'method', ['pause', 'resume', 'stop', 'step', 'multi_act', 'rerun_history', 'load_and_rerun', 'save_history']
)
def test_removed_agent_methods_raise_one_error(method, no_browser):
	agent = Agent('t', script()[0])
	with pytest.raises(AttributeError, match=rf'^Agent\.{method}\(\) {REMOVED}'):
		getattr(agent, method)
	assert not hasattr(agent, method)
	with pytest.raises(AttributeError, match='no attribute'):
		agent.definitely_not_a_method


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
		with pytest.raises(ImportError, match=rf'^browser_use\.{name} {REMOVED}'):
			getattr(browser_use, name)
	for name in ['ChatGroq', 'ChatOllama', 'ChatAzureOpenAI', 'ChatOpenRouter', 'ChatDeepSeek']:
		with pytest.raises(ImportError, match=rf"{REMOVED} In 1\.0: a Pydantic AI model string, e\.g\. llm='groq:"):
			exec(f'from browser_use import {name}')
		with pytest.raises(ImportError, match=rf'^browser_use\.llm\.{name} {REMOVED} In 1\.0: '):
			exec(f'from browser_use.llm import {name}')  # the common 0.x import path
	with pytest.raises(ImportError, match='cannot import name'):
		exec('from browser_use.llm import NotAThing')


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


@pytest.mark.parametrize('name', ['urls', 'screenshots', 'action_names', 'model_thoughts', 'history', 'judgement', 'is_judged'])
def test_removed_result_methods_raise_not_implemented(name):
	with pytest.raises(NotImplementedError, match=rf'^AgentHistoryList\.{name} {REMOVED} In 1\.0: '):
		getattr(result(), name)
	with pytest.raises(AttributeError):
		result().definitely_not_a_method


def test_removed_result_classmethod_raises_on_the_class():
	"""0.x AgentHistoryList.load_from_file(path) was a classmethod: called on the class, not an instance."""
	with pytest.raises(NotImplementedError, match=rf'^AgentHistoryList\.load_from_file {REMOVED} In 1\.0: '):
		AgentHistoryList.load_from_file('history.json')


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
	with pytest.raises(TypeError, match=rf'^Injected action parameters \({param} in @tools\.action act\(\)\) {REMOVED}'):
		exec(f'@tools.action("x")\nasync def act(text: str, {param}=None): pass', {'tools': tools})


def test_tools_domain_filters_and_reserved_names_raise():
	tools = Tools()
	for name in ('domains', 'allowed_domains'):
		with pytest.raises(TypeError, match=rf'^@tools\.action\({name}=\.\.\.\) {REMOVED} In 1\.0: Browser\(allowed_domains'):
			tools.action('x', **{name: ['*.example.com']})
	with pytest.raises(ValueError, match='built-in'):

		@tools.action('x')
		def finish(result: str):
			return result


async def test_custom_action_is_a_model_tool(tmp_path):
	tools = Tools()

	@tools.action('Price of a product')
	def get_price(sku: str) -> ActionResult:
		return ActionResult(extracted_content=f'{sku} costs 9.99')

	model, seen = script(('get_price', {'sku': 'A1'}), ('finish', {'success': True, 'result': 'done'}))
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

	model, seen = script(('account', {}), ('note', {}), ('check', {}), ('finish', {'success': True, 'result': 'done'}))
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
	model, _ = script(('finish', {'success': True, 'result': 'done'}))
	assert (await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')).is_successful() is True


async def test_finish_requires_a_success_verdict(tmp_path):
	"""agent-llm F1: success defaulted to True, so an impossible task finished without a verdict came back
	is_successful() == True (3/3 runs). Like 0.x done(success), finish and finish_from_repl now require it."""
	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.models.function import FunctionModel

	turns = [{'result': 'The book does not exist.'}, {'result': 'The book does not exist.', 'success': False}]
	seen = []

	def fn(messages, info):
		seen.append(({t.name: t.parameters_json_schema for t in info.output_tools}, messages[-1]))
		return ModelResponse(parts=[ToolCallPart('finish', turns[len(seen) - 1])])

	model = FunctionModel(fn)
	r = await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert all('success' in schema['required'] for schema in seen[0][0].values()), seen[0][0]
	assert 'success' in str(seen[1][1])  # the omitted verdict went back to the model as a retry
	assert (r.status, r.output, r.is_successful()) == ('completed', 'The book does not exist.', False)


@pytest.mark.parametrize('budget', [{'max_steps': 0}, {'max_steps': -1}, {'max_steps': 2.5}, {'timeout': 0}, {'timeout': -5}])
async def test_impossible_budgets_raise_before_any_browser(budget, no_browser):
	"""agent-llm: run(max_steps=0) and run(timeout<=0) started (and billed) a browser, then ended in an error."""
	with pytest.raises(ValueError, match='max_steps' if 'max_steps' in budget else 'timeout'):
		await Agent('t', script()[0], browser=Browser(local=True)).run(**budget)


async def test_structured_final_result_is_the_models_json(tmp_path):
	"""Roast C10: final_result() was '"title=\'x\' points=3"' (str() of the model) instead of 0.x model_dump_json()."""

	class Story(BaseModel):
		title: str
		points: int

	model, _ = script(('finish', {'success': True, 'result': {'title': 'x', 'points': 3}}))
	r = await run(build_agent(model, output_type=Story), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert r.final_result() == Story(title='x', points=3).model_dump_json()
	assert r.structured_output == Story(title='x', points=3)


@pytest.mark.parametrize('schema', ['literal', 'strenum'])
async def test_structured_output_of_a_str_valued_schema(schema, fake_browser, tmp_path):
	"""M8: structured_output was None for Literal and StrEnum schemas: it only checked isinstance(output, str)."""
	from enum import StrEnum
	from typing import Literal

	class Answer(StrEnum):
		yes = 'yes'
		no = 'no'

	output_type = Literal['yes', 'no'] if schema == 'literal' else Answer
	model, _ = script(('finish', {'success': True, 'result': 'yes'}))
	agent = Agent('t', model, browser=Browser(local=True), output_model_schema=output_type, workspace=tmp_path)
	r = await agent.run()
	assert r.structured_output == 'yes' and r.final_result() == 'yes'
	model, _ = script(('finish', {'success': True, 'result': 'plain'}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()).structured_output is None


async def test_a_tools_own_timeout_is_an_error_not_the_run_budget(tmp_path):
	"""Fable: socket.timeout is TimeoutError; it was reported as status='timeout', error=None with budget unused. The
	model now gets it as the tool's error (H2) and the run goes on."""
	tools = Tools()

	@tools.action('Fetch a URL')
	def fetch(url: str) -> str:
		raise TimeoutError('timed out')

	model, seen = script(('fetch', {'url': 'https://x.test'}), ('finish', {'success': False, 'result': 'fetch timed out'}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.status, r.error, r.output) == ('completed', None, 'fetch timed out')
	assert 'TimeoutError: timed out' in str(seen[1][-1])


async def test_a_custom_tool_that_raises_returns_the_error_to_the_model(tmp_path):
	"""H2: a custom tool raising an ordinary exception ended the whole run; 0.x returned ActionResult(error=...) to the
	model. Sync and async tools, with and without sensitive_data."""
	tools = Tools()

	@tools.action('Look up a price')
	def price(sku: str) -> str:
		raise KeyError(f'no such sku {sku}')

	@tools.action('Look up stock')
	async def stock(sku: str) -> str:
		raise ValueError('stock service down hunter2-Zq9')

	for secrets in (None, {'pw': 'hunter2-Zq9'}):
		model, seen = script(
			('price', {'sku': 'A1'}), ('stock', {'sku': 'A1'}), ('finish', {'success': False, 'result': 'unknown'})
		)
		r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path, secrets=secrets)), 'm')
		assert (r.status, r.output) == ('completed', 'unknown'), r.error
		assert "KeyError: 'no such sku A1'" in str(seen[1][-1])
		assert 'ValueError: stock service down' in str(seen[2][-1])
		if secrets:
			assert 'hunter2-Zq9' not in str(seen) and '<secret:pw>' in str(seen[2][-1])


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

	model, seen = script(('place_order', {'params': {'sku': 'A1', 'qty': '3'}}), ('finish', {'success': True, 'result': 'done'}))
	await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert '3x A1' in str(seen[1][-1])


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


async def test_two_agents_never_run_on_one_browser_at_once(fake_browser, tmp_path):
	"""H5: two Agents on one Browser drove one tab, and the first to finish stopped the browser under the other. The
	second run now raises before it starts anything; one after another (keep_alive) still works."""
	import asyncio

	browser = Browser(local=True, keep_alive=True)
	slow, _ = script(('python', {'code': 'import time; time.sleep(1)'}), ('finish', {'success': True, 'result': 'one'}))
	quick, _ = script(('finish', {'success': True, 'result': 'two'}), ('finish', {'success': True, 'result': 'three'}))
	first = Agent('t', slow, browser=browser, workspace=tmp_path / 'a')
	second = Agent('t', quick, browser=browser, workspace=tmp_path / 'b')
	try:
		r1, r2 = await asyncio.gather(first.run(), second.run(), return_exceptions=True)
		assert isinstance(r2, RuntimeError) and 'in use by another running Agent' in str(r2)
		assert not isinstance(r1, BaseException) and r1.final_result() == 'one'
		assert (await second.run()).final_result() == 'two'  # one after another is fine
	finally:
		await first.close()
		await second.close()


def test_run_sync_follow_up_keeps_the_repl_with_keep_alive(fake_browser, tmp_path):
	# 0.x scripts call run_sync() twice; the REPL worker belongs to the first call's event loop.
	model, _ = script(
		('python', {'code': 'x = 41'}),
		('finish', {'success': True, 'result': 'one'}),
		('finish_from_repl', {'success': True, 'expression': 'str(x + 1)'}),
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
	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	runner_loop, repl = agent._runner.get_loop(), agent._repl
	agent.close_sync()
	assert agent._runner is None and runner_loop.is_closed() and agent._repl is None
	assert repl.proc is None


async def test_failed_follow_up_still_stops_the_browser(fake_browser, monkeypatch, tmp_path):
	model, _ = script(('finish', {'success': True, 'result': 'one'}))
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
	from pydantic_ai.models.function import FunctionModel

	secret = 'hunter2-Zq9'

	def provider(messages, info):  # a custom tool's exception goes back to the model (H2): the provider's ends the run
		raise RuntimeError(f'login failed for password {secret}')

	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(FunctionModel(provider)), 'task', session, 'm')
	assert r.status == 'error' and r.error == 'RuntimeError: login failed for password <secret:pw>'


async def test_failed_run_fallback_output_never_shows_a_secret(tmp_path):
	"""Roast r5-1: a text reply quoting a secret, then a provider failure: the fallback became raw result.output."""
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.models.function import AgentInfo, FunctionModel

	secret = 'hunter2-Zq9'
	calls = []

	def reply(messages, info: AgentInfo) -> ModelResponse:
		calls.append(1)
		if len(calls) == 1:
			return ModelResponse(parts=[TextPart(f'The password is {secret}')])
		raise RuntimeError('provider down')

	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(FunctionModel(reply)), 'task', session, 'm')
	assert r.status == 'error'
	assert secret not in str(r.output) and secret not in r.text and '<secret:pw>' in str(r.output)


def test_cost_is_the_price_of_the_model_that_answered():
	"""H12: Gemini was priced as the requested alias (gemini-3.5-flash) while the response came from (and was billed as)
	gemini-3.6-flash: about 2.3x too high. An unknown served name falls back to the requested one."""
	from genai_prices import calc_price
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	u = RequestUsage(input_tokens=1_000_000, output_tokens=100_000)
	served = float(calc_price(u, model_ref='gemini-2.5-flash', provider_id='google').total_price)
	requested = float(calc_price(u, model_ref='gemini-2.5-pro', provider_id='google').total_price)
	answer = ModelResponse(parts=[TextPart('x')], usage=u, model_name='gemini-2.5-flash')
	assert usage_and_cost([answer], 'google-gla:gemini-2.5-pro')[1] == pytest.approx(served) != pytest.approx(requested)
	unknown = ModelResponse(parts=[TextPart('x')], usage=u, model_name='gemini-made-up-snapshot-9')
	assert usage_and_cost([unknown], 'google-gla:gemini-2.5-pro')[1] == pytest.approx(requested)


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


async def test_secrets_in_the_task_never_reach_the_model(fake_browser, tmp_path):
	"""Roast r3-2: Agent(f'Log in with {password}', sensitive_data=...) sent the password in the first request (0.x
	replaced it with the secret's name); follow-up tasks and extend_system_message too."""
	secret = 'hunter2-Zq9'
	model, seen = script(('finish', {'success': True, 'result': 'one'}), ('finish', {'success': True, 'result': 'two'}))
	agent = Agent(
		f'Log in with {secret}',
		model,
		browser=Browser(local=True),
		sensitive_data={'pw': secret},
		extend_system_message=f'The password is {secret}.',
		workspace=tmp_path,
	)
	await agent.run()
	agent.add_new_task(f'Again with {secret}')
	await agent.run()
	assert secret not in str(seen) and 'Log in with <secret:pw>' in str(seen[0]) and 'Again with <secret:pw>' in str(seen[1])
	assert 'The password is <secret:pw>.' in str(seen[0])


async def test_overlapping_runs_on_one_agent_are_rejected(fake_browser, tmp_path):
	"""Roast r3-6: two concurrent run() calls on one Agent each created a REPL (one never closed) and either could
	stop the other's browser."""
	import asyncio

	model, _ = script(('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True), workspace=tmp_path)
	first, second = await asyncio.gather(agent.run(), agent.run(), return_exceptions=True)
	assert isinstance(second, RuntimeError) and 'already running' in str(second)
	assert first.final_result() == 'one' and len(fake_browser) == 1  # only the first run started and stopped
	assert (await agent.run()).status == 'error'  # the next run is allowed again (the script has no third turn)


@pytest.mark.parametrize('reasoning', ['max', 'Medium', True])
def test_unknown_reasoning_raises_before_any_browser(reasoning, no_browser):
	"""Fable r3-2: reasoning was stored unchecked; a typo started (and billed) a cloud browser, then the first model
	request failed with a 400."""
	with pytest.raises(ValueError, match='reasoning'):
		Agent('t', 'test', reasoning=reasoning)


async def test_old_mcp_tool_names_return_the_removed_error():
	from mcp import types

	from browser_use.mcp import cli_mcp

	handler = cli_mcp.CLIMCPServer().server._request_handlers['tools/call'].handler
	for name in ('browser_navigate', 'browser_click', 'retry_with_browser_use_agent'):
		r = await handler(None, types.CallToolRequestParams(name=name, arguments={}))
		text = r.content[0].text  # type: ignore[union-attr]
		assert r.is_error and text.startswith(
			f'The MCP tool {name} (the 0.x browser-use --mcp server) was removed in browser-use 1.0.'
		)
		assert 'browser_exec runs Python' in text
	r = await handler(None, types.CallToolRequestParams(name='nope', arguments={}))
	assert r.content[0].text == 'Unknown tool: nope'  # type: ignore[union-attr]
