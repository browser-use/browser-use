"""Tests for browser_use.harness -- canned daemon transport + scripted LLM, no Chrome.

Not in tests/ci: needs browser-harness >= 0.1.9 (sdk extra), which the package still pins below.
"""

import json

import pytest

pytest.importorskip('browser_harness.sdk', reason='requires browser-harness >= 0.1.9 with the sdk extra')

from browser_harness.sdk import Browser, HarnessError
from pydantic import BaseModel

from browser_use.harness import Agent, Tools
from browser_use.harness.views import HarnessElement, HarnessState
from browser_use.llm.views import ChatInvokeCompletion


def _val(value):
	return {'result': {'result': {'value': value}}}


class FakeBrowserBackend:
	"""Canned daemon: enough CDP surface for the agent loop, tracking state."""

	def __init__(self):
		self.url = 'about:blank'
		self.title = 'Shop'
		self.calls = []
		self.clicks = []
		self.field_value = None  # what input verification reads back; None = skip verification
		self.fingerprint = None  # click before/after fingerprint; same object twice = no-op click
		self.fingerprint_after = None
		self._fp_calls = 0

	async def send(self, req, request_timeout=None):
		self.calls.append(req)
		if 'meta' in req:
			meta = req['meta']
			if meta == 'pending_dialog':
				return {}
			if meta == 'current_tab':
				return {'targetId': 'TARGET-AAAA', 'title': self.title, 'url': self.url}
			if meta == 'session':
				return {'session_id': 'S1'}
			if meta == 'drain_events':
				return {'events': []}
			return {}
		method = req['method']
		params = req.get('params', {})
		if method == 'Page.navigate':
			self.url = params['url']
			return {'result': {'frameId': 'f'}}
		if method == 'Runtime.evaluate':
			expr = params['expression']
			if 'document.readyState' in expr:
				return _val('complete')
			if 'JSON.stringify({url:location.href' in expr:
				return _val(
					json.dumps(
						{'url': self.url, 'title': self.title, 'w': 1280, 'h': 800, 'sx': 0, 'sy': 0, 'pw': 1280, 'ph': 2000}
					)
				)
			if 'innerText' in expr:
				return _val('Welcome to the shop. Buy now.')
			return _val(None)
		if method == 'Accessibility.getFullAXTree':
			return {
				'result': {
					'nodes': [
						{'backendDOMNodeId': 11, 'role': {'value': 'button'}, 'name': {'value': 'Buy now'}},
						{'backendDOMNodeId': 12, 'role': {'value': 'link'}, 'name': {'value': 'Cart'}},
						{'backendDOMNodeId': 13, 'role': {'value': 'heading'}, 'name': {'value': 'Deals'}},
					]
				}
			}
		if method == 'Target.getTargets':
			return {
				'result': {'targetInfos': [{'type': 'page', 'targetId': 'TARGET-AAAA', 'title': self.title, 'url': self.url}]}
			}
		if method == 'Target.createTarget':
			self.url = params.get('url', 'about:blank')
			return {'result': {'targetId': 'TARGET-NEW1'}}
		if method == 'Target.attachToTarget':
			return {'result': {'sessionId': 'S-NEW'}}
		if method == 'DOM.getBoxModel':
			return {'result': {'model': {'content': [0, 0, 100, 0, 100, 40, 0, 40]}}}
		if method == 'Input.dispatchMouseEvent':
			self.clicks.append((params['type'], params['x'], params['y']))
			return {'result': {}}
		if method == 'DOM.resolveNode':
			return {'result': {'object': {'objectId': 'obj1'}}}
		if method == 'Runtime.callFunctionOn':
			fn = params.get('functionDeclaration', '')
			if "'value' in this" in fn:  # input verification readback
				return {'result': {'result': {'value': self.field_value}}}
			if 'elementFromPoint' in fn:  # click fingerprint
				import json as _json

				if self.fingerprint is None:
					return {'result': {'result': {'value': None}}}
				self._fp_calls += 1
				fp = self.fingerprint if (self._fp_calls % 2 == 1 or not self.fingerprint_after) else self.fingerprint_after
				return {'result': {'result': {'value': _json.dumps(fp)}}}
			if 'closest' in fn and 'options' in fn:  # select_option
				return {'result': {'result': {'value': 'selected ' + (params.get('arguments') or [{}])[0].get('value', '')}}}
			return {'result': {'result': {'value': True}}}
		# DOM.scrollIntoViewIfNeeded, DOM.focus, Input.dispatchKeyEvent, ...
		return {'result': {}}


class ScriptedLLM:
	"""BaseChatModel-compatible: replays a script of AgentOutput dicts."""

	model = 'scripted'

	def __init__(self, script: list[dict]):
		self.script = list(script)
		self.call_messages = []

	@property
	def provider(self) -> str:
		return 'scripted'

	@property
	def name(self) -> str:
		return 'scripted'

	@property
	def model_name(self) -> str:
		return 'scripted'

	async def ainvoke(self, messages, output_format=None, **kwargs):
		assert output_format is not None, 'harness agent always requests structured output'
		self.call_messages.append(messages)
		assert self.script, 'LLM called more times than scripted'
		step = self.script.pop(0)
		return ChatInvokeCompletion(completion=output_format.model_validate(step), usage=None)


def make_fake_browser() -> tuple[Browser, FakeBrowserBackend]:
	browser = Browser(auto_start=False)
	browser._started = True
	backend = FakeBrowserBackend()
	browser.client.send = backend.send

	async def _no_daemon_start():
		return browser

	browser.start = _no_daemon_start
	return browser, backend


def make_state(elements: list[HarnessElement] | None = None) -> HarnessState:
	return HarnessState(url='https://shop.test/', title='Shop', elements=elements or [])


# --- Tools registry ---


async def test_custom_action_registers_and_dispatches():
	tools = Tools()
	browser, _ = make_fake_browser()

	@tools.action('Count orders above a total')
	async def order_count(min_total: float = 0.0, browser: Browser = None) -> str:  # type: ignore[assignment]
		assert browser is not None
		return f'3 orders over {min_total}'

	assert 'order_count' in tools.registry
	action_model = tools.create_action_model()
	assert 'order_count' in action_model.model_fields

	action = action_model.model_validate({'order_count': {'min_total': 10.5}})
	result = await tools.act(action, browser=browser, state=make_state())
	assert result.extracted_content == '3 orders over 10.5'
	assert result.error is None


async def test_act_reports_unknown_index_as_error_not_exception():
	tools = Tools()
	browser, backend = make_fake_browser()
	action = tools.create_action_model().model_validate({'click': {'index': 99}})
	result = await tools.act(action, browser=browser, state=make_state())
	assert result.error is not None and '99' in result.error
	assert backend.clicks == []


async def test_click_dispatches_mouse_events_at_element_center():
	tools = Tools()
	browser, backend = make_fake_browser()
	element = HarnessElement(index=1, role='button', name='Buy now', backend_node_id=11)
	action = tools.create_action_model().model_validate({'click': {'index': 1}})
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is None
	assert backend.clicks == [('mousePressed', 50, 20), ('mouseReleased', 50, 20)]


async def test_prompt_description_lists_params():
	tools = Tools()
	description = tools.get_prompt_description()
	assert 'navigate:' in description
	assert 'url=string' in description
	assert 'done:' in description


async def test_write_read_file_roundtrip(tmp_path):
	tools = Tools()
	browser, _ = make_fake_browser()
	model = tools.create_action_model()

	write = model.model_validate({'write_file': {'file_name': 'data.json', 'content': 'part1-'}})
	result = await tools.act(write, browser=browser, state=make_state(), file_dir=tmp_path)
	assert result.error is None and 'Wrote 6 chars' in result.extracted_content

	append = model.model_validate({'write_file': {'file_name': 'data.json', 'content': 'part2', 'append': True}})
	await tools.act(append, browser=browser, state=make_state(), file_dir=tmp_path)
	assert (tmp_path / 'data.json').read_text() == 'part1-part2'

	read = model.model_validate({'read_file': {'file_name': 'data.json'}})
	result = await tools.act(read, browser=browser, state=make_state(), file_dir=tmp_path)
	assert 'part1-part2' in result.extracted_content

	missing = model.model_validate({'read_file': {'file_name': 'nope.txt'}})
	result = await tools.act(missing, browser=browser, state=make_state(), file_dir=tmp_path)
	assert result.error is not None and 'data.json' in result.error  # lists what exists


async def test_evaluate_save_as_persists_untruncated_result(tmp_path):
	from browser_use.harness.tools import EVALUATE_DISPLAY_CAP

	big = 'x' * (EVALUATE_DISPLAY_CAP + 5000)
	tools = Tools()
	browser, backend = make_fake_browser()
	backend_send = browser.client.send

	async def send(req, request_timeout=None):
		if req.get('method') == 'Runtime.evaluate' and 'x' not in req['params']['expression']:
			return {'result': {'result': {'value': big}}}
		return await backend_send(req, request_timeout)

	browser.client.send = send
	action = tools.create_action_model().model_validate({'evaluate': {'code': 'grab()', 'save_as': 'dump.txt'}})
	result = await tools.act(action, browser=browser, state=make_state(), file_dir=tmp_path)
	assert (tmp_path / 'dump.txt').read_text() == big  # full, no truncation
	assert 'TRUNCATED' in result.extracted_content and 'dump.txt' in result.extracted_content
	assert 'read_file' in result.long_term_memory  # the surviving note must point back at the file


async def test_input_verification_flags_controlled_widgets():
	tools = Tools()
	browser, backend = make_fake_browser()
	backend.field_value = 'China, 73301Austin'  # widget corrupted the field
	element = HarnessElement(index=1, role='textbox', name='From', backend_node_id=11)
	action = tools.create_action_model().model_validate({'input': {'index': 1, 'text': 'Austin'}})
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is not None and 'verification failed' in result.error

	backend.field_value = 'Austin'  # clean write passes
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is None


async def test_click_reports_no_observable_effect():
	"""A click that changes nothing must say so -- silent success let one run click
	the same dead radio 18 times while the model kept noting it wasn't working."""
	tools = Tools()
	browser, backend = make_fake_browser()
	backend.fingerprint = {'url': 'https://shop.test/', 'checked': False, 'len': 100, 'hit': 'DIV.overlay'}
	element = HarnessElement(index=1, role='radio', name='Off', backend_node_id=11)
	action = tools.create_action_model().model_validate({'click': {'index': 1}})
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is None
	assert 'NO OBSERVABLE EFFECT' in result.extracted_content
	assert 'DIV.overlay' in result.extracted_content  # names what actually got the click

	backend.fingerprint_after = {'url': 'https://shop.test/', 'checked': True, 'len': 100, 'hit': None}
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert 'NO OBSERVABLE EFFECT' not in result.extracted_content


async def test_index_error_suggests_the_prefix_match():
	"""Bad indices are the right index with digits appended (139 -> 1396582)."""
	tools = Tools()
	browser, _ = make_fake_browser()
	state = make_state([HarnessElement(index=139, role='link', name='Volume 17', backend_node_id=11)])
	action = tools.create_action_model().model_validate({'click': {'index': 1396582}})
	result = await tools.act(action, browser=browser, state=state)
	assert result.error is not None
	assert 'valid indices are 1..' in result.error and '139' in result.error


async def test_done_refused_once_when_unread_files_may_hold_the_answer(tmp_path):
	tools = Tools()
	browser, _ = make_fake_browser()
	(tmp_path / 'prices.json').write_text('{"price": "$1029.99"}')
	model = tools.create_action_model()
	done = model.model_validate({'done': {'text': 'Price: not available in extracted evidence', 'success': True}})

	first = await tools.act(done, browser=browser, state=make_state(), file_dir=tmp_path)
	assert first.error is not None and 'prices.json' in first.error
	assert not first.is_done

	second = await tools.act(done, browser=browser, state=make_state(), file_dir=tmp_path)
	assert second.is_done  # one-shot: never blocks the agent from ever finishing


async def test_multi_field_action_runs_both_instead_of_killing_the_step(tmp_path):
	"""'do X and save it' packed into one action used to raise and void the step."""
	tools = Tools()
	browser, _ = make_fake_browser()
	action = tools.create_action_model().model_validate(
		{'scroll': {'pages': 1.0}, 'write_file': {'file_name': 'notes.txt', 'content': 'kept'}}
	)
	result = await tools.act(action, browser=browser, state=make_state(), file_dir=tmp_path)
	assert result.error is None
	assert (tmp_path / 'notes.txt').read_text() == 'kept'
	assert 'Scrolled' in result.extracted_content


async def test_select_dropdown_dispatches_change():
	tools = Tools()
	browser, _ = make_fake_browser()
	element = HarnessElement(index=5, role='combobox', name='State', backend_node_id=11)
	action = tools.create_action_model().model_validate({'select_dropdown': {'index': 5, 'text': 'OHIO'}})
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is None and result.extracted_content == 'selected OHIO'


async def test_box_model_error_becomes_actionable_guidance():
	tools = Tools()
	browser, backend = make_fake_browser()
	original = browser.client.send

	async def send(req, request_timeout=None):
		if req.get('method') == 'DOM.getBoxModel':
			# what HarnessClient.send raises for this daemon error
			raise HarnessError("{'code': -32000, 'message': 'Could not compute box model.'}")
		return await original(req, request_timeout)

	browser.client.send = send
	element = HarnessElement(index=1, role='option', name='OHIO', backend_node_id=11)
	action = tools.create_action_model().model_validate({'click': {'index': 1}})
	result = await tools.act(action, browser=browser, state=make_state([element]))
	assert result.error is not None and 'select_dropdown' in result.error


# --- Agent loop ---


def make_agent(script: list[dict], **kwargs) -> tuple[Agent, FakeBrowserBackend, ScriptedLLM]:
	browser, backend = make_fake_browser()
	llm = ScriptedLLM(script)
	agent = Agent(task='Buy the widget', llm=llm, browser=browser, use_vision=False, **kwargs)
	return agent, backend, llm


async def test_agent_runs_navigate_click_done():
	agent, backend, llm = make_agent(
		[
			{
				'evaluation_previous_goal': 'start',
				'memory': '',
				'next_goal': 'open the shop',
				'action': [{'navigate': {'url': 'https://shop.test/'}}, {'click': {'index': 1}}],
			},
			{
				'evaluation_previous_goal': 'navigated',
				'memory': 'on shop page',
				'next_goal': 'buy',
				'action': [{'click': {'index': 1}}],
			},
			{
				'evaluation_previous_goal': 'clicked buy',
				'memory': 'purchase made',
				'next_goal': 'finish',
				'action': [{'done': {'text': 'Bought the widget', 'success': True}}],
			},
		]
	)
	history = await agent.run(max_steps=10)

	assert history.is_done() is True
	assert history.is_successful() is True
	assert history.final_result() == 'Bought the widget'
	assert history.number_of_steps() == 3
	# navigate terminates the sequence -- the click queued after it must not run
	assert backend.clicks == [('mousePressed', 50, 20), ('mouseReleased', 50, 20)]
	step1_actions = history.model_actions()
	assert 'navigate' in history.action_names()
	assert backend.url == 'https://shop.test/'
	assert history.urls()[1] == 'https://shop.test/'
	# llm saw the indexed elements -- heading role filtered out, button+link kept
	state_text = llm.call_messages[1][-1].text
	assert "[1]<button 'Buy now'>" in state_text
	assert "[2]<link 'Cart'>" in state_text
	assert 'heading' not in state_text
	assert len(step1_actions) >= 3


async def test_full_results_reach_the_next_prompt_then_compress():
	"""Extractions must survive into the next step verbatim -- losing them made agents
	re-extract the same page 14-25 times and then answer from a truncated prefix."""
	payload = 'PRICE-MARKER ' + 'y' * 3000
	agent, backend, llm = make_agent(
		[
			{
				'evaluation_previous_goal': 'start',
				'memory': '',
				'next_goal': 'extract',
				'action': [{'evaluate': {'code': 'grab()'}}],
			},
			{'evaluation_previous_goal': 'got it', 'memory': '', 'next_goal': 'again', 'action': [{'wait': {'seconds': 0.01}}]},
			{
				'evaluation_previous_goal': 'x',
				'memory': '',
				'next_goal': 'finish',
				'action': [{'done': {'text': 'ok', 'success': True}}],
			},
		]
	)
	original = browser_send = agent.browser.client.send

	async def send(req, request_timeout=None):
		if req.get('method') == 'Runtime.evaluate' and req['params']['expression'] == 'grab()':
			return {'result': {'result': {'value': payload}}}
		return await original(req, request_timeout)

	agent.browser.client.send = send
	await agent.run(max_steps=5)

	step2_prompt = '\n'.join(m.text for m in llm.call_messages[1])
	assert payload in step2_prompt, 'full extraction must be carried into the next prompt'
	step3_prompt = '\n'.join(m.text for m in llm.call_messages[2])
	assert payload not in step3_prompt, 'full text is shown once, then only the compressed note'
	assert 'PRICE-MARKER' in step3_prompt, 'the compressed note must still reference what was found'


async def test_budget_pressure_and_repeat_warning_reach_the_model():
	repeat = {
		'evaluation_previous_goal': 'x',
		'memory': '',
		'next_goal': 'retry',
		'action': [{'click': {'index': 99}}],
	}
	agent, _, llm = make_agent([repeat] * 6, max_failures=99)
	await agent.run(max_steps=6)

	prompts = ['\n'.join(m.text for m in msgs) for msgs in llm.call_messages]
	assert any('repeated the same action' in p for p in prompts), 'identical-action loop must be called out'
	assert any('steps remain' in p and 'call' in p for p in prompts), 'budget pressure must reach the model'


async def test_agent_structured_output():
	class Product(BaseModel):
		title: str
		price: float

	agent, _, _ = make_agent(
		[
			{
				'evaluation_previous_goal': 'start',
				'memory': '',
				'next_goal': 'answer',
				'action': [{'done': {'success': True, 'data': {'title': 'Widget', 'price': 9.5}}}],
			}
		],
		output_model_schema=Product,
	)
	history = await agent.run(max_steps=3)

	assert history.is_successful() is True
	product = history.structured_output
	assert product == Product(title='Widget', price=9.5)
	# schema is advertised to the llm via the task text
	assert 'Expected output format: Product' in agent.task


async def test_agent_stops_after_consecutive_failures():
	bad_step = {
		'evaluation_previous_goal': 'x',
		'memory': '',
		'next_goal': 'x',
		'action': [{'click': {'index': 99}}],
	}
	agent, _, llm = make_agent([bad_step, bad_step, bad_step, bad_step, bad_step], max_failures=2)
	history = await agent.run(max_steps=10)

	assert history.is_done() is False
	assert history.has_errors() is True
	assert len(llm.script) == 3  # stopped after 2 failing steps, not all 5
	assert any('consecutive failures' in (e or '') for e in history.errors())


async def test_agent_rejects_browser_and_browser_session():
	browser, _ = make_fake_browser()
	with pytest.raises(ValueError, match='browser_session'):
		Agent(task='x', llm=ScriptedLLM([]), browser=browser, browser_session=browser)


async def test_agent_max_steps_records_failure_item():
	step = {
		'evaluation_previous_goal': 'x',
		'memory': '',
		'next_goal': 'keep going',
		'action': [{'wait': {'seconds': 0.01}}],
	}
	agent, _, _ = make_agent([step, step])
	history = await agent.run(max_steps=2)

	assert history.is_done() is False
	assert any('maximum steps' in (e or '') for e in history.errors())


# --- browser_use API compatibility ---


def test_browser_use_import_line_works():
	"""`from browser_use.harness import Agent, Browser, Tools, ChatOpenAI` — the
	same one-liner browser_use users write."""
	from browser_use.harness import Agent, Browser, ChatBrowserUse, ChatOpenAI, Controller, SyncBrowser, Tools

	assert Controller is Tools
	assert all(x is not None for x in (Agent, Browser, SyncBrowser, ChatOpenAI, ChatBrowserUse))


def test_browser_session_aliases_exist_on_harness_browser():
	"""browser_use.BrowserSession code should run unchanged against the harness."""
	from browser_harness.sdk import Browser as HB

	for name in (
		'navigate_to',
		'get_tabs',
		'get_current_page_url',
		'get_current_page_title',
		'take_screenshot',
		'close',
		'kill',
		'cookies',
		'from_system_chrome',
	):
		assert callable(getattr(HB, name)), f'missing BrowserSession alias: {name}'


async def test_direct_tool_calls_without_an_llm():
	"""browser_use.Tools lets you call actions directly; so does this."""
	tools = Tools()
	browser, backend = make_fake_browser()
	result = await tools.navigate(url='https://shop.test/', browser=browser)
	assert result.error is None
	assert backend.url == 'https://shop.test/'


def test_defaults_match_browser_use_agent():
	import inspect

	from browser_use import Agent as BUAgent

	bu = inspect.signature(BUAgent.__init__).parameters
	h = inspect.signature(Agent.__init__).parameters
	for name in ('max_actions_per_step', 'max_failures', 'step_timeout'):
		assert bu[name].default == h[name].default, f'{name} default differs'
	assert inspect.signature(BUAgent.run).parameters['max_steps'].default == (
		inspect.signature(Agent.run).parameters['max_steps'].default
	)


def test_action_vocabulary_matches_browser_use():
	from browser_use import Tools as BUTools

	bu = set(BUTools().registry.registry.actions)
	h = set(Tools().registry)
	missing = bu - h
	assert missing <= {'save_as_pdf'}, f'harness is missing browser_use actions: {sorted(missing)}'
	assert h - bu <= {'handle_dialog'}, f'harness has unexpected extra actions: {sorted(h - bu)}'


async def test_capture_recovers_from_a_wedged_page():
	"""A blocked JS thread makes every Runtime.evaluate hang, so a plain retry
	hangs too -- one traced run died at step 5 re-issuing the same call. The
	agent must escalate to another tab rather than retry into the wedge."""
	agent, backend, _ = make_agent([])
	backend.url = 'https://shop.test/'
	backend.recovered = False
	original = backend.send

	async def send(req, request_timeout=None):
		if req.get('method') == 'Target.createTarget':
			backend.recovered = True  # escaped to a fresh tab
		if req.get('method') == 'Runtime.evaluate' and not backend.recovered:
			raise TimeoutError('Runtime.evaluate timed out')
		return await original(req, request_timeout)

	agent.browser.client.send = send
	state = await agent._capture_state()
	assert backend.recovered, 'a wedged tab must be escaped, not retried into'
	assert state.state_error is None, 'recovery should have produced a real observation'


async def test_unrecoverable_page_yields_state_error_not_a_dead_step():
	"""If nothing works the agent still gets a turn, as browser_use does with
	state_error -- a lost step teaches the model nothing."""
	agent, backend, _ = make_agent([])

	async def send(req, request_timeout=None):
		if req.get('method') == 'Runtime.evaluate':
			raise TimeoutError('Runtime.evaluate timed out')
		return await backend.send(req, request_timeout)

	agent.browser.client.send = send
	state = await agent._capture_state()
	assert state.state_error and 'blocked' in state.state_error
	message = agent._state_message(state, 3, 35)
	assert 'blocked' in message.text  # and it reaches the model


def test_flash_mode_uses_browser_use_flash_schema():
	from browser_use.agent.views import AgentOutput

	agent, _, _ = make_agent([], flash_mode=True)
	schema = agent.AgentOutput.model_json_schema()
	assert set(schema['required']) == {'memory', 'action'}, schema['required']
	assert 'thinking' not in schema['properties']
	# and it is genuinely browser_use's flash schema, not just thinking disabled
	expected = AgentOutput.type_with_custom_actions_flash_mode(agent.ActionModel).model_json_schema()
	assert schema['required'] == expected['required']


def test_default_request_timeout_matches_the_cli():
	"""The CLI's socket timeout is 5s; a longer SDK default turns a wedged page
	into a 30s stall per call."""
	from browser_harness.sdk import Browser as HB

	assert HB().client.request_timeout == 5.0
