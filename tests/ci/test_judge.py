"""The judge: one request to the agent's own model after each run (Agent(judge=False) turns it off)."""

import json

import pytest
from conftest import script
from pydantic import ValidationError

import browser_use.agent.service as service
from browser_use import Agent, Browser
from browser_use.agent.judge import JUDGE_PROMPT, Judgement
from browser_use.agent.views import AgentHistoryList

VERDICT = {
	'success': True,
	'failure_reason': None,
	'description': 'Opened the page and reported the price.',
	'prompt_injection_detected': False,
	'bot_block_or_captcha_detected': True,
	'gotchas': ['Open the home page before a product page, else a bot check shows.'],
}
FINISH = ('finish', {'success': True, 'result': 'done'})


@pytest.fixture
def fake_browser(monkeypatch):
	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)


@pytest.fixture
def sent(monkeypatch):
	"""The properties each agent_event would send, built as the telemetry thread builds them."""
	import browser_use.telemetry.service as telemetry

	events = []

	class FakeTelemetry:
		enabled = True

		def run_started(self, run_id, props, progress):
			pass

		def capture_run(self, job):
			events.append(job.build(200, 50))

	monkeypatch.setattr(telemetry, 'telemetry', FakeTelemetry)
	return events


def agent(model, tmp_path, **kwargs):
	return Agent('find the price', model, browser=Browser(local=True), workspace=tmp_path, **kwargs)


async def test_each_run_is_judged_once_by_the_agents_own_model(fake_browser, tmp_path):
	"""One more turn of the run: its messages and instructions go first, so the provider reads them from its cache."""
	model, seen = script(FINISH, json.dumps(VERDICT))
	r = await agent(model, tmp_path).run()
	assert len(seen) == 2  # the run's one request and the judge's
	assert r.judgement == Judgement(**VERDICT)
	assert r.usage['requests'] == 2
	run_request, judge_request = seen[0][-1], seen[1][-1]
	assert seen[1][: len(seen[0]) - 1] == seen[0][:-1] and judge_request.instructions == run_request.instructions
	assert JUDGE_PROMPT in judge_request.parts[-1].content[0]
	assert '<task>\nfind the price\n</task>' in judge_request.parts[-1].content[0]


@pytest.mark.parametrize('off', [{'judge': False}, {'use_judge': False}])
async def test_judge_false_sends_no_judge_request(off, fake_browser, tmp_path):
	model, seen = script(FINISH)
	r = await agent(model, tmp_path, **off).run()
	assert (len(seen), r.judgement, r.usage['requests']) == (1, None, 1)


async def test_a_failed_judge_leaves_the_run_as_it_was_and_is_still_counted(fake_browser, tmp_path):
	"""A judge answer that does not fit the schema is not retried (one judge request); its tokens are still counted."""
	model, seen = script(FINISH, '{"success": "maybe"}', ('final_result', {'success': 'maybe'}))
	r = await agent(model, tmp_path).run()
	assert (r.status, r.text, r.judgement, len(seen), r.usage['requests']) == ('completed', 'done', None, 3, 3)


async def test_the_judge_request_is_bounded(fake_browser, tmp_path):
	from browser_use.agent.judge import MAX_PART_CHARS, MAX_TASK_CHARS, MAX_TRACE_CHARS

	model, seen = script(FINISH, json.dumps(VERDICT))
	huge = 'word ' * 200_000
	await Agent(huge, model, browser=Browser(local=True), workspace=tmp_path, judge_context=huge).run()
	assert len(str(seen[1][-1].parts[-1].content)) < MAX_TRACE_CHARS + 2 * MAX_TASK_CHARS + 2 * MAX_PART_CHARS + 1000


async def test_a_responses_model_is_judged_streamed_at_low_effort(monkeypatch):
	"""A gateway bu-* alias has no effort in the loop's settings (its own applies): the judge asks for low."""
	from types import SimpleNamespace

	from pydantic_ai.models.openai import OpenAIResponsesModel
	from pydantic_ai.providers.openai import OpenAIProvider

	import browser_use.agent.judge as judge
	from browser_use.agent.judge import judge_run
	from browser_use.agent.loop import StreamedRequest

	built = {}

	class Recorded:
		def __init__(self, model, **kwargs):
			built.update(kwargs, model=model)

		async def run(self, text):
			raise RuntimeError('no provider in tests')

	monkeypatch.setattr(judge, 'Agent', Recorded)
	model = OpenAIResponsesModel('gpt-6-luna', provider=OpenAIProvider(api_key='k'))
	loop_agent = SimpleNamespace(model=model, model_settings={'openai_store': False, 'tool_choice': 'required'})
	result = AgentHistoryList('completed', 'done', 'done', 1, 1.0, {}, None, None, None, [], True)
	assert await judge_run(loop_agent, 't', result, None, {}) == (None, [])
	assert isinstance(built['model'], StreamedRequest)
	assert built['model_settings'] == {'openai_store': False, 'openai_reasoning_effort': 'low'}
	assert built['retries'] == {'output': 0}


def test_the_schema_rejects_an_incomplete_judgement():
	with pytest.raises(ValidationError):
		Judgement.model_validate({'success': True})
	assert Judgement.model_validate({**VERDICT, 'gotchas': []}).gotchas == []


async def test_the_judges_tokens_and_cost_are_added_to_the_run(monkeypatch, tmp_path):
	model, seen = script(('final_result', VERDICT))
	a = agent(model, tmp_path)
	a._build()
	usage = {'input': 100, 'output': 10, 'cache_read': 0, 'cache_write': 0, 'requests': 1}
	result = AgentHistoryList('completed', 'done', 'done', 1, 1.0, usage, 1.0, None, None, [], True)
	judged = {'input': 7, 'output': 3, 'cache_read': 0, 'cache_write': 0, 'requests': 1}
	monkeypatch.setattr(service, 'usage_and_cost', lambda messages, ref: (judged, 0.25))
	await a._judge(result)
	assert result.cost_usd == 1.25
	assert dict(result.usage) == {'input': 107, 'output': 13, 'cache_read': 0, 'cache_write': 0, 'requests': 2}
	for run_cost, judge_cost in ((None, 0.25), (1.0, None)):  # an unknown cost stays unknown
		model, seen = script(('final_result', VERDICT))
		b = agent(model, tmp_path)
		b._build()
		result.cost_usd, result.judgement = run_cost, None
		monkeypatch.setattr(service, 'usage_and_cost', lambda messages, ref, c=judge_cost: (judged, c))
		await b._judge(result)
		assert (len(seen), result.judgement is not None, result.cost_usd) == (1, True, None)


def test_more_than_five_gotchas_keep_the_first_five():
	assert Judgement.model_validate({**VERDICT, 'gotchas': [str(i) for i in range(8)]}).gotchas == list('01234')


def test_0x_judge_class_names_point_to_result_judgement():
	import browser_use.agent.judge as judge

	with pytest.raises(AttributeError, match=r'result\.judgement'):
		judge.JudgementResult


def test_the_prompt_forbids_personal_data_and_secrets():
	for words in ('emails', 'personal', 'credentials', 'secrets', 'URLs are fine'):
		assert words in JUDGE_PROMPT


async def test_secrets_never_reach_the_judge_or_its_answer(fake_browser, tmp_path):
	secret = 'hunter2-Zq9x'
	leaky = {**VERDICT, 'gotchas': [f'The password {secret} works']}
	model, seen = script(FINISH, json.dumps(leaky))
	r = await Agent(
		f'log in with {secret}', model, browser=Browser(local=True), workspace=tmp_path, sensitive_data={'pw': secret}
	).run()
	assert secret not in str(seen[1])
	assert r.judgement and r.judgement.gotchas == ['The password <secret:pw> works']


async def test_the_whole_judgement_is_sent_scrubbed_when_telemetry_is_on(sent, fake_browser, tmp_path):
	leaky = {**VERDICT, 'gotchas': ['Write to jane.doe@example.com for access', 'Wait 2 s after search']}
	leaky['description'] = 'It found that the price is 10 on the page.'  # judge_context, never sent
	model, _ = script(FINISH, json.dumps(leaky))
	await agent(model, tmp_path, judge_context='the price is 10').run()
	(event,) = sent
	assert (event['judge'], event['judge_context']) == (True, True)
	judgement = event['judgement']
	assert judgement['gotchas'] == ['Write to <email> for access', 'Wait 2 s after search']
	assert {k: judgement[k] for k in ('success', 'bot_block_or_captcha_detected')} == {
		'success': True,
		'bot_block_or_captcha_detected': True,
	}
	assert 'cost_usd' in judgement
	assert 'the price is 10' not in str(event)


async def test_with_telemetry_off_nothing_is_sent(sent, fake_browser, tmp_path, monkeypatch):
	import browser_use.telemetry.service as telemetry

	monkeypatch.setattr(telemetry.telemetry, 'enabled', False)
	model, _ = script(FINISH, json.dumps(VERDICT))
	r = await agent(model, tmp_path).run()
	assert r.judgement and sent == []


def test_0x_ground_truth_is_the_judge_context(tmp_path):
	assert agent(script()[0], tmp_path, ground_truth='the price is 10').judge_context == 'the price is 10'
	with pytest.raises(TypeError, match='judge must be True or False'):
		agent(script()[0], tmp_path, judge='yes')


def test_the_judge_gets_the_last_distinct_screenshots_and_the_final_page():
	from pydantic_ai import BinaryContent
	from pydantic_ai.messages import ModelRequest, ToolReturnPart

	from browser_use.agent.judge import MAX_SCREENSHOTS, screenshots

	def shot(n):
		return BinaryContent(bytes([n]) * 8, media_type='image/jpeg')

	def cell(*images):
		return ModelRequest(parts=[ToolReturnPart('python', ['out', *images], tool_call_id='c')])

	messages = [cell(shot(1)), cell(shot(2), shot(3)), cell(shot(3)), cell(shot(4))]  # 3 twice: an unchanged page
	assert [s.data[0] for s in screenshots(messages)] == [1, 2, 3, 4]
	assert MAX_SCREENSHOTS == 4 and [s.data[0] for s in screenshots(messages, shot(5))] == [2, 3, 4, 5]  # the final page counts
	assert [s.data[0] for s in screenshots(messages, shot(4))] == [1, 2, 3, 4]  # the final page as the last screenshot
	assert screenshots([]) == []


async def test_the_screenshots_go_to_the_judge_as_images_after_the_text(monkeypatch):
	from types import SimpleNamespace

	from pydantic_ai import BinaryContent
	from pydantic_ai.models.test import TestModel

	import browser_use.agent.judge as judge
	from browser_use.agent.judge import judge_run

	sent = []

	class Recorded:
		def __init__(self, model, **kwargs):
			pass

		async def run(self, content):
			sent.append(content)
			raise RuntimeError('no provider in tests')

	monkeypatch.setattr(judge, 'Agent', Recorded)
	loop_agent = SimpleNamespace(model=TestModel(), model_settings={})
	result = AgentHistoryList('completed', 'done', 'done', 1, 1.0, {}, None, None, None, [], True)
	final = BinaryContent(b'page', media_type='image/jpeg')
	await judge_run(loop_agent, 't', result, None, {}, final)
	await judge_run(loop_agent, 't', result, None, {})
	assert sent[0][1:] == ['Screenshot 1 of 1, oldest first.', final] and '<task>' in sent[0][0]
	assert isinstance(sent[1], str)  # no screenshots: the text alone


async def test_a_text_only_model_that_rejects_the_images_is_judged_from_the_text(monkeypatch):
	from types import SimpleNamespace

	from pydantic_ai import BinaryContent
	from pydantic_ai.exceptions import ModelHTTPError
	from pydantic_ai.models.test import TestModel

	import browser_use.agent.judge as judge
	from browser_use.agent.judge import judge_run

	sent = []

	class TextOnly:
		def __init__(self, model, **kwargs):
			pass

		async def run(self, content):
			sent.append(content)
			if not isinstance(content, str):
				raise ModelHTTPError(400, 'm', {'error': 'image input is not supported'} if not sent[1:] else {'error': 'x'})
			return SimpleNamespace(output=Judgement.model_validate(VERDICT), all_messages=lambda: ['judged'])

	monkeypatch.setattr(judge, 'Agent', TextOnly)
	result = AgentHistoryList('completed', 'done', 'done', 1, 1.0, {}, None, None, None, [], True)
	final = BinaryContent(b'page', media_type='image/jpeg')
	judgement, messages = await judge_run(SimpleNamespace(model=TestModel(), model_settings={}), 't', result, None, {}, final)
	assert judgement is not None and judgement.success and messages == ['judged']
	assert [type(c) for c in sent] == [list, str]


async def test_the_final_page_is_taken_through_the_daemon_and_never_fails_the_run(fake_browser, tmp_path, monkeypatch):
	import base64

	import browser_use.browser.browser as browser_module

	asked = []

	def daemon(name, request, timeout=30):
		if request.get('meta') == 'session':
			return {'session_id': 'page-session'}
		asked.append(request['method'])
		if request['method'] == 'Runtime.evaluate':
			return {'result': {'result': {'value': 'visible'}}}
		return {'result': {'data': base64.b64encode(b'jpeg').decode()}}

	monkeypatch.setattr(browser_module, '_daemon_request', daemon)
	model, seen = script(FINISH, json.dumps(VERDICT))
	result = await agent(model, tmp_path).run()
	assert result.judgement is not None and asked == ['Runtime.evaluate', 'Page.captureScreenshot']
	assert seen[1][-1].parts[-1].content[-1].data == b'jpeg'

	def gone(name, request, timeout=30):
		raise ConnectionError('no daemon')

	monkeypatch.setattr(browser_module, '_daemon_request', gone)
	model, seen = script(FINISH, json.dumps(VERDICT))
	assert (await agent(model, tmp_path).run()).judgement is not None
	assert len(seen[1][-1].parts[-1].content) == 1  # no final page: the text alone

	asked.clear()
	monkeypatch.setattr(browser_module, '_daemon_request', daemon)
	model, seen = script(FINISH)
	await agent(model, tmp_path, judge=False).run()
	model, seen = script(FINISH, json.dumps(VERDICT))
	await agent(model, tmp_path, use_vision=False).run()
	assert asked == []  # judge=False or use_vision=False: no capture


async def test_an_error_that_is_not_about_images_is_not_retried(monkeypatch):
	from types import SimpleNamespace

	from pydantic_ai import BinaryContent
	from pydantic_ai.exceptions import ModelHTTPError
	from pydantic_ai.models.test import TestModel

	import browser_use.agent.judge as judge
	from browser_use.agent.judge import judge_run

	sent = []

	class Missing:
		def __init__(self, model, **kwargs):
			pass

		async def run(self, content):
			sent.append(content)
			raise ModelHTTPError(404, 'm', {'error': 'model not found'})

	monkeypatch.setattr(judge, 'Agent', Missing)
	result = AgentHistoryList('completed', 'done', 'done', 1, 1.0, {}, None, None, None, [], True)
	final = BinaryContent(b'page', media_type='image/jpeg')
	assert (await judge_run(SimpleNamespace(model=TestModel(), model_settings={}), 't', result, None, {}, final))[0] is None
	assert len(sent) == 1


def test_a_hidden_tab_is_not_captured(monkeypatch):
	import browser_use.browser.browser as browser_module
	from browser_use import Browser

	asked = []

	def daemon(name, request, timeout=30):
		if request.get('meta') == 'session':
			return {'session_id': 'page-session'}
		asked.append(request['method'])
		return {'result': {'result': {'value': 'hidden'}}}

	monkeypatch.setattr(browser_module, '_daemon_request', daemon)
	assert Browser(local=True)._screenshot(10) is None
	assert asked == ['Runtime.evaluate']  # never activated, never captured


async def test_the_final_screenshot_stays_on_the_session_checked_visible(daemon, fake_browser, tmp_path, monkeypatch):
	"""Another shared-daemon client switches tabs between the visibility check and capture: the judge must still see
	the checked page, not that client's page."""
	import io

	from PIL import Image

	import browser_use.browser.browser as browser_module

	name = daemon['BU_NAME']
	request = browser_module._daemon_request
	original = request(name, {'meta': 'connection_status'})

	def cdp(method, session_id=None, **params):
		return browser_module._daemon_cdp(name, method, session_id=session_id, **params)

	pages = []
	try:
		for color in ('red', 'blue'):
			target = cdp('Target.createTarget', url='about:blank', newWindow=True)['targetId']
			session = cdp('Target.attachToTarget', targetId=target, flatten=True)['sessionId']
			pages.append((target, session))
			cdp('Runtime.evaluate', session_id=session, expression=f'document.body.style.background = {color!r}')
		(first, first_session), (other, other_session) = pages
		for _, session in pages:
			assert (
				cdp('Runtime.evaluate', session_id=session, expression='document.visibilityState')['result']['value'] == 'visible'
			)
		request(name, {'meta': 'set_session', 'session_id': first_session, 'target_id': first})
		switched = []

		def switch_after_visibility(daemon_name, payload, timeout=30):
			response = request(daemon_name, payload, timeout=timeout)
			if payload.get('method') == 'Runtime.evaluate' and payload['params'].get('expression') == 'document.visibilityState':
				request(name, {'meta': 'set_session', 'session_id': other_session, 'target_id': other})
				switched.append(True)
			return response

		monkeypatch.setattr(browser_module, '_daemon_request', switch_after_visibility)
		model, seen = script(FINISH, ('final_result', VERDICT))
		a = agent(model, tmp_path)
		a.browser.name = name
		result = await a.run()
		assert result.judgement is not None and switched == [True]
		shot = seen[1][0].parts[0].content[-1]
		red, _, blue = Image.open(io.BytesIO(shot.data)).convert('RGB').getpixel((20, 20))
		assert red > 200 and blue < 30, (red, blue)
	finally:
		request(name, {'meta': 'set_session', 'session_id': original['session_id'], 'target_id': original['target_id']})
		for target, _ in pages:
			cdp('Target.closeTarget', targetId=target)
