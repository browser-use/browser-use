"""The judge: one request to the agent's own model after each run (Agent(judge=False) turns it off)."""

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
	model, seen = script(FINISH, ('final_result', VERDICT))
	r = await agent(model, tmp_path).run()
	assert len(seen) == 2  # the run's one request and the judge's
	assert r.judgement == Judgement(**VERDICT)
	assert r.usage['requests'] == 2
	judge_request = seen[1][0]
	assert JUDGE_PROMPT in judge_request.instructions
	assert '<task>\nfind the price\n</task>' in str(judge_request.parts[0].content)


@pytest.mark.parametrize('off', [{'judge': False}, {'use_judge': False}])
async def test_judge_false_sends_no_judge_request(off, fake_browser, tmp_path):
	model, seen = script(FINISH)
	r = await agent(model, tmp_path, **off).run()
	assert (len(seen), r.judgement, r.usage['requests']) == (1, None, 1)


async def test_a_failed_judge_leaves_the_run_as_it_was_and_is_still_counted(fake_browser, tmp_path):
	"""A judge answer that does not fit the schema is not retried (one judge request); its tokens are still counted."""
	model, seen = script(FINISH, ('final_result', {'success': 'maybe'}))
	r = await agent(model, tmp_path).run()
	assert (r.status, r.text, r.judgement, len(seen), r.usage['requests']) == ('completed', 'done', None, 2, 2)


async def test_the_judge_request_is_bounded(fake_browser, tmp_path):
	from browser_use.agent.judge import MAX_PART_CHARS, MAX_TASK_CHARS, MAX_TRACE_CHARS

	model, seen = script(FINISH, ('final_result', VERDICT))
	huge = 'word ' * 200_000
	await Agent(huge, model, browser=Browser(local=True), workspace=tmp_path, judge_context=huge).run()
	assert len(str(seen[1][0].parts[0].content)) < MAX_TRACE_CHARS + 2 * MAX_TASK_CHARS + 2 * MAX_PART_CHARS + 1000


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
	model, seen = script(FINISH, ('final_result', leaky))
	r = await Agent(
		f'log in with {secret}', model, browser=Browser(local=True), workspace=tmp_path, sensitive_data={'pw': secret}
	).run()
	assert secret not in str(seen[1])
	assert r.judgement and r.judgement.gotchas == ['The password <secret:pw> works']


async def test_the_whole_judgement_is_sent_scrubbed_when_telemetry_is_on(sent, fake_browser, tmp_path):
	leaky = {**VERDICT, 'gotchas': ['Write to jane.doe@example.com for access', 'Wait 2 s after search']}
	leaky['description'] = 'It found that the price is 10 on the page.'  # judge_context, never sent
	model, _ = script(FINISH, ('final_result', leaky))
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
	model, _ = script(FINISH, ('final_result', VERDICT))
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
	assert [s.data[0] for s in screenshots(messages, shot(5))] == [2, 3, 4, 5][-MAX_SCREENSHOTS:]
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


async def test_the_final_screenshot_never_fails_the_judge():
	import base64

	from browser_use.agent.judge import final_screenshot

	class Repl:
		def __init__(self, answer):
			self.answer = answer

		async def call(self, op, code, timeout):
			if isinstance(self.answer, Exception):
				raise self.answer
			return self.answer

	image = {'data': base64.b64encode(b'jpeg').decode(), 'media_type': 'image/jpeg'}
	shot = await final_screenshot(Repl({'error': None, 'images': [image]}))
	assert shot is not None and shot.data == b'jpeg' and shot.media_type == 'image/jpeg'
	assert await final_screenshot(Repl({'error': 'BrowserConnectionLost', 'images': []})) is None
	assert await final_screenshot(Repl(ConnectionError('worker'))) is None
	assert await final_screenshot(None) is None


def test_the_prompt_asks_for_gotchas_on_a_success_too():
	assert 'on a success as on a failure' in JUDGE_PROMPT and 'write at least one' in JUDGE_PROMPT
