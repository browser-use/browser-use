"""Tests for browser_use.harness -- canned daemon transport + scripted LLM, no Chrome.

Not in tests/ci: needs browser-harness >= 0.1.9 (sdk extra), which the package still pins below.
"""

import json

import pytest

pytest.importorskip('browser_harness.sdk', reason='requires browser-harness >= 0.1.9 with the sdk extra')

from browser_harness.sdk import Browser
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

	async def send(self, req):
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
		if method == 'DOM.getBoxModel':
			return {'result': {'model': {'content': [0, 0, 100, 0, 100, 40, 0, 40]}}}
		if method == 'Input.dispatchMouseEvent':
			self.clicks.append((params['type'], params['x'], params['y']))
			return {'result': {}}
		if method == 'DOM.resolveNode':
			return {'result': {'object': {'objectId': 'obj1'}}}
		if method == 'Runtime.callFunctionOn':
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
