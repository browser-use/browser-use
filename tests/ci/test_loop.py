"""The agent loop end-to-end against a real isolated headless Chrome, scripted model (no provider calls)."""

import json
from pathlib import Path

import pytest
from conftest import script
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_compaction import FakeRepl

from browser_use.agent.loop import Session, build_agent, run
from browser_use.repl import Repl


class LastMessages:
	"""seen[i] = the last message of model request i (what BUP's tests index)."""

	def __init__(self, requests):
		self.requests = requests

	def __getitem__(self, i):
		return self.requests[i][-1]

	def __len__(self):
		return len(self.requests)


async def go(env, tmp_path, steps, **kw):
	model, requests = script(*steps)
	seen = LastMessages(requests)
	agent = build_agent()
	session = Session(repl=Repl(tmp_path, env), **kw)
	try:
		with agent.override(model=model):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	return result, seen


async def test_browser_screenshot_and_finish_from_repl(daemon, tmp_path):
	result, seen = await go(
		daemon,
		tmp_path,
		[
			(
				'python',
				{
					'code': "new_tab('data:text/html,<title>T</title><h1>Hello</h1>')\nwait_for_load()\n"
					'info = page_info()\nh = js(\'document.querySelector("h1").textContent\')\nscreenshot()\nh'
				},
			),
			(
				'python',
				{'code': 'records = [{"h": h, "title": info["title"]}]\nawait __import__("asyncio").sleep(0)\nlen(records)'},
			),
			('finish_from_repl', {'success': True, 'expression': 'json.dumps(records)'}),
		],
	)
	assert result.status == 'completed', result.error
	assert json.loads(result.output) == [{'h': 'Hello', 'title': 'T'}]
	first = [p for p in seen[1].parts if isinstance(p, ToolReturnPart)][0]
	assert first.content[0].strip() == 'Hello'
	assert any(getattr(c, 'is_image', False) for c in first.content)  # native image to the model
	assert [p for p in seen[2].parts if isinstance(p, ToolReturnPart)][0].content[0].strip() == '1'


async def test_cell_timeout_restarts_worker_keeps_files(daemon, tmp_path):
	result, seen = await go(
		daemon,
		tmp_path,
		[
			(
				'python',
				{
					'code': "x = 1\ncheckpoint('rows.json', [1, 2], partial=True)\nprint('saved', flush=True)\nimport time\ntime.sleep(30)"
				},
			),
			('python', {'code': "print('x' in globals(), json.load(open('rows.json')))"}),
			('python', {'code': 'raise ValueError("boom")'}),
			('finish', {'success': True, 'result': 'done'}),
		],
		cell_timeout_s=3,
	)
	assert result.output == 'done'
	timed_out = [p for p in seen[1].parts if isinstance(p, ToolReturnPart)][0].content[0]
	assert 'saved' in timed_out and 'timed out' in timed_out
	assert [p for p in seen[2].parts if isinstance(p, ToolReturnPart)][0].content[0].strip() == 'False [1, 2]'
	assert 'ValueError: boom' in [p for p in seen[3].parts if isinstance(p, ToolReturnPart)][0].content[0]


async def test_timeout_returns_partial(daemon, tmp_path):
	import asyncio

	turns = [
		ModelResponse(parts=[ToolCallPart('python', {'code': "checkpoint('out.json', {'rows': 3}, partial=True)"})]),
		ModelResponse(parts=[ToolCallPart('python', {'code': 'import time\ntime.sleep(30)'})]),  # cut where delivery starts
	]

	async def fn(messages, info: AgentInfo):
		if turns:
			return turns.pop(0)
		await asyncio.sleep(30)  # the delivery request outlives the budget too
		raise AssertionError('unreachable')

	session = Session(repl=Repl(tmp_path, daemon), timeout_s=4, cell_timeout_s=60)
	try:
		result = await run(build_agent(FunctionModel(fn)), 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert result.status == 'timeout'
	assert json.loads(result.text) == {'rows': 3}


async def test_only_last_two_screenshot_results_keep_images(daemon, tmp_path):
	shot = ('python', {'code': "new_tab('data:text/html,<h1>x</h1>') if not list_tabs(False) else None\nscreenshot()\n'shot'"})
	result, seen = await go(daemon, tmp_path, [shot, shot, shot, ('finish', {'success': True, 'result': 'ok'})])
	assert result.output == 'ok'
	returns = [
		p for m in result.messages for p in getattr(m, 'parts', []) if isinstance(p, ToolReturnPart) and p.tool_name == 'python'
	]
	images = [sum(getattr(c, 'is_image', False) for c in p.content) for p in returns]
	assert images == [0, 1, 1]
	assert '[older screenshot removed]' in returns[0].content


async def test_use_vision_false_sends_no_image(daemon, tmp_path):
	"""Review: C17 ignored 0.x use_vision=False, so screenshots a user turned off for privacy, cost or a text-only model
	reached the provider."""
	shot = ('python', {'code': "new_tab('data:text/html,<h1>x</h1>')\nscreenshot()\n'shot'"})
	result, seen = await go(daemon, tmp_path, [shot, ('finish', {'success': True, 'result': 'ok'})], vision=False)
	part = next(p for p in seen[1].parts if isinstance(p, ToolReturnPart))
	assert result.status == 'completed' and all(isinstance(c, str) for c in part.content)
	assert 'use_vision=False' in part.content[0]


async def test_parallel_python_calls_are_serialized(daemon, tmp_path):
	# hard-high 0vgnxb/74rs7g/up8ijl: two python calls in one response crashed the run (readuntil race)
	calls = [0]

	def fn(messages, info: AgentInfo):
		calls[0] += 1
		if calls[0] == 1:
			return ModelResponse(
				parts=[
					ToolCallPart('python', {'code': 'import time; time.sleep(0.3); a = 1'}),
					ToolCallPart('python', {'code': 'b = 2'}),
				]
			)
		return ModelResponse(parts=[ToolCallPart('finish_from_repl', {'success': True, 'expression': 'str(a + b)'})])

	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=FunctionModel(fn)):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert (result.status, result.output, result.error) == ('completed', '3', None)


async def test_oversized_and_invalid_images_never_reach_provider(daemon, tmp_path):
	# v2 bub2-002 (43200 patches > 30000) and hard y0bvr6 (invalid image data) 400'd the whole run
	code = (
		"from PIL import Image; Image.new('RGB', (1440, 30000), 'white').save('tall.png'); "
		"open('bad.png', 'wb').write(b'\\x89PNG not really'); print(show_image('tall.png'), show_image('bad.png'))"
	)
	result, seen = await go(daemon, tmp_path, [('python', {'code': code}), ('finish', {'success': True, 'result': 'ok'})])
	part = next(p for p in seen[1].parts if isinstance(p, ToolReturnPart))
	images = [c for c in part.content if not isinstance(c, str)]
	assert result.status == 'completed' and len(images) == 1
	import io

	from PIL import Image

	assert max(Image.open(io.BytesIO(images[0].data)).size) <= 2048
	assert 'not a decodable image' in part.content[0]


@pytest.mark.parametrize(
	'errors, sdk_retries, status, calls, slept',
	[
		(['rate'], 0, 'completed', 2, [2]),  # once more, after the provider's Retry-After
		(['server', 'overloaded'], 0, 'error', 2, [0]),  # once per run, as bu-pi
		(['rejected'], 0, 'error', 1, []),  # a 400 is not sent again
		(['rate'], 2, 'error', 1, []),  # the OpenAI/Anthropic SDK client already retried it twice
		(['grpc_unavailable'], 0, 'error', 1, []),  # xai-sdk's gRPC retry policy already sent it 5 times
	],
)
async def test_transient_provider_error_is_retried_once(tmp_path, monkeypatch, errors, sdk_retries, status, calls, slept):
	"""grok bub2-007: xAI's 429 "model is currently at capacity" ended the run at step 38 with no retry (its gRPC client
	retries only UNAVAILABLE; pydantic-ai raises ModelRateLimitError). bu-pi retries such a request once per run."""
	import asyncio
	from types import SimpleNamespace

	from pydantic_ai import exceptions as x

	make = {
		'rate': lambda: x.ModelRateLimitError('grok-4.7', 'The model is currently at capacity', retry_after=2),
		'server': lambda: x.ModelServerError('grok-4.7', 'internal'),
		'overloaded': lambda: x.ModelOverloadedError('grok-4.7', 'overloaded'),
		'rejected': lambda: x.ModelRequestRejectedError('grok-4.7', 'invalid_image'),
		'grpc_unavailable': lambda: x.ModelUnavailableError('grok-4.7', 'unavailable', provider_error_code='UNAVAILABLE'),
	}
	pending, sleeps, requests, real_sleep = list(errors), [], [], asyncio.sleep

	async def sleep(delay, *args):
		sleeps.append(delay)
		await real_sleep(0)

	def fn(messages, info: AgentInfo):
		requests.append(1)
		if pending:
			raise make[pending.pop(0)]()
		return ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': 'ok'})])

	model = FunctionModel(fn)
	model._system = 'xai'
	if sdk_retries:
		model.client = SimpleNamespace(max_retries=sdk_retries)  # pyright: ignore[reportAttributeAccessIssue]
	monkeypatch.setattr(asyncio, 'sleep', sleep)
	agent, session = build_agent(), Session(repl=Repl(tmp_path))
	try:
		with agent.override(model=model):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert (result.status, len(requests), sleeps) == (status, calls, slept), result.error


async def test_workspace_path_is_in_instructions(daemon, tmp_path):
	seen = []

	def fn(messages, info: AgentInfo):
		seen.append(info.instructions)
		return ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': 'ok'})])

	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=FunctionModel(fn)):
			await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert json.dumps(str(tmp_path.resolve())) in seen[0] and 'never `await` them' in seen[0]


async def test_text_reply_is_the_answer_for_a_str_result(daemon, tmp_path):
	"""C33: the default str result took the answer only after a delivery-repair request (bu-pi), which gpt-6-luna needed
	on 21 of 22 runs. Its text reply is now the answer: no extra request, no verdict."""
	from pydantic_ai.messages import TextPart

	seen = []

	def fn(messages, info: AgentInfo):
		seen.append(messages[-1])
		if len(seen) == 1:
			return ModelResponse(parts=[ToolCallPart('python', {'code': 'rows = [1, 2, 3]'})])
		return ModelResponse(parts=[TextPart('I found 3 rows.')])

	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=FunctionModel(fn)):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert len(seen) == 2
	assert (result.status, result.output, session.finish_via, session.success) == ('completed', 'I found 3 rows.', 'text', None)


async def test_structured_text_reply_gets_one_delivery_repair_turn(daemon, tmp_path):
	# A text-only reply used to be impossible (tool_choice=required every turn). Now it is allowed; with a structured
	# result, ending the work in text triggers bu-pi's single delivery-repair turn with delivery tools forced.
	from pydantic_ai.messages import RetryPromptPart, TextPart
	from pydantic_ai.models import ModelRequestParameters
	from pydantic_ai.models._tool_choice import resolve_tool_choice

	from browser_use.agent.loop import DELIVERY_REPAIR

	seen = []

	def fn(messages, info: AgentInfo):
		params = ModelRequestParameters(
			function_tools=info.function_tools, output_tools=info.output_tools, allow_text_output=info.allow_text_output
		)
		seen.append((messages[-1], resolve_tool_choice(info.model_settings, params)))
		if len(seen) == 1:
			return ModelResponse(parts=[ToolCallPart('python', {'code': 'rows = [1, 2, 3]'})])
		if len(seen) == 2:
			return ModelResponse(parts=[TextPart('I found 3 rows.')])
		return ModelResponse(parts=[ToolCallPart('finish_from_repl', {'success': True, 'expression': 'json.dumps(rows)'})])

	agent, session = build_agent(output_type=list[int]), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=FunctionModel(fn)):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert [c for _, c in seen[:2]] == ['auto', 'auto']  # the model may stop and talk
	repair_msg, repair_choice = seen[2]
	assert any(
		DELIVERY_REPAIR in (p.model_response() if isinstance(p, RetryPromptPart) else str(getattr(p, 'content', '')))
		for p in repair_msg.parts
	)
	assert repair_choice == ('required', {'finish', 'finish_from_repl'})
	assert (result.status, result.output) == ('completed', [1, 2, 3])


async def test_a_tool_call_on_the_delivery_turn_is_not_run(daemon, tmp_path):
	"""M2: where python is only withheld from the delivery-only turn (Claude), the model still called it (2/2 runs, one
	ended empty). The call is now refused, unvalidated, and the model delivers on the next request."""
	from browser_use.agent.loop import NOT_RUN

	model, seen = script(
		('python', {'code': 'x = 1'}),
		[('python', {'code': "open('ran.txt', 'w').write('yes')"}), ('python', {})],  # the 2nd lacks 'code'
		('finish', {'success': True, 'result': 'done'}),
	)
	session = Session(repl=Repl(tmp_path, daemon), max_steps=2)
	try:
		result = await run(build_agent(model), 'task', session, 'm')
	finally:
		await session.repl.close()
	assert (result.status, result.output) == ('completed', 'done'), result.error
	assert not (tmp_path / 'ran.txt').exists() and str(seen[2][-1]).count(NOT_RUN) == 2


async def test_a_short_timeout_still_leaves_time_to_deliver(daemon, tmp_path):
	"""M5: run(timeout=25) returned nothing: a cell could run to the budget's end, and the delivery turn got the last
	10% (2.5 s). Cells now stop where the delivery turn starts, which a short budget moves earlier."""
	model, _ = script(
		('python', {'code': 'import time; time.sleep(30)'}),
		('finish', {'success': False, 'result': 'ran out of time'}),
	)
	session = Session(repl=Repl(tmp_path, daemon), timeout_s=8)
	try:
		result = await run(build_agent(model), 'task', session, 'm')
	finally:
		await session.repl.close()
	assert (result.status, result.output) == ('completed', 'ran out of time'), result.error
	assert result.duration_s < 8 and session.budget_hit == 'timeout'
	assert Session(repl=session.repl, timeout_s=1700).delivery_at() == pytest.approx(1530)  # default budget unchanged


async def test_an_open_js_dialog_is_named_instead_of_timing_out(daemon, tmp_path):
	"""M15: with an alert open, js() took 20 s, click_at_xy 20 s and screenshot() 65 s, with errors that did not say why."""
	import time

	repl = Repl(tmp_path, daemon)
	try:
		r = await repl.call(
			'exec', "new_tab('data:text/html,<p>x'); wait_for_load(); js('setTimeout(() => alert(\"hi\"), 50)')", 60
		)
		assert r['error'] is None, r
		for code in ('import time; time.sleep(1); js("1")', 'screenshot()'):
			started = time.monotonic()
			r = await repl.call('exec', code, 60)
			assert time.monotonic() - started < 8, code
			assert 'A JavaScript alert is open' in (r['error'] or '') and 'Page.handleJavaScriptDialog' in r['error'], r
		r = await repl.call('exec', 'cdp("Page.handleJavaScriptDialog", accept=True); print(js("1 + 1"))', 60)
		assert r['error'] is None and '2' in r['output'], r
		# a call that opens the dialog itself times out, then names it
		r = await repl.call('exec', 'cdp("Runtime.evaluate", expression="alert(1)", _response_timeout=2)', 60)
		assert 'A JavaScript alert is open' in (r['error'] or ''), r
		await repl.call('exec', 'cdp("Page.handleJavaScriptDialog", accept=True)', 60)
	finally:
		await repl.close()


def _choice_recorder(responses):
	from pydantic_ai.models import ModelRequestParameters
	from pydantic_ai.models._tool_choice import resolve_tool_choice

	seen = []

	def fn(messages, info: AgentInfo):
		params = ModelRequestParameters(
			function_tools=info.function_tools, output_tools=info.output_tools, allow_text_output=info.allow_text_output
		)
		seen.append((messages, resolve_tool_choice(info.model_settings, params)))
		return responses[len(seen) - 1]

	return FunctionModel(fn), seen


async def test_budget_turn_forces_delivery_on_the_same_request(daemon, tmp_path):
	# v1b let one more python call through after "Budget nearly exhausted" (settings resolved before the hook);
	# in 4n89qk/t4p501 that turn was spent and the forced finish came one turn late.
	from browser_use.agent.loop import DELIVER_NOW

	model, seen = _choice_recorder(
		[
			ModelResponse(parts=[ToolCallPart('python', {'code': 'x = 1'})]),
			ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': 'one'})]),
		]
	)
	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon), max_steps=2)
	try:
		with agent.override(model=model):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert seen[0][1] == 'auto'
	assert DELIVER_NOW in str(seen[1][0][-1]) and seen[1][1] == ('required', {'finish', 'finish_from_repl'})
	# A budget-cut run still returns status='completed'; the verdict is the caller's only signal (0.x asked for it).
	assert 'success=false' in str(seen[1][0][-1])
	assert result.output == 'one'


@pytest.mark.parametrize('max_steps', [1, 3])
async def test_max_steps_leaves_all_but_the_last_request_for_the_browser(daemon, tmp_path, max_steps):
	"""C57: max_steps=N ran N-2 cells (delivery at request N-1, repair at N) and N < 3 raised; 0.x ran N-1 steps
	and made the last one the forced done, so max_steps=1 only delivers."""
	from browser_use.agent.loop import DELIVER_NOW

	cell = ('python', {'code': "open('cells.txt', 'a').write('x')"})
	model, seen = script(*[cell] * (max_steps - 1), ('finish', {'success': True, 'result': 'done'}))
	session = Session(repl=Repl(tmp_path, daemon), max_steps=max_steps)
	try:
		result = await run(build_agent(model), 'task', session, 'm')
	finally:
		await session.repl.close()
	assert (result.status, result.output) == ('completed', 'done'), result.error
	cells = tmp_path / 'cells.txt'
	assert (cells.read_text() if cells.exists() else '') == 'x' * (max_steps - 1)
	assert DELIVER_NOW in str(seen[max_steps - 1][-1]) and session.budget_hit == 'max_steps'


@pytest.mark.parametrize('first', ['...', 'Saved: [leads](leads.csv)', 'Saved in the workspace: `leads.csv`'])
async def test_placeholder_or_missing_file_delivery_gets_one_repair(daemon, tmp_path, first):
	# 4n89qk delivered finish("..."); t4p501 linked leads_verified.csv that was never written.
	model, seen = _choice_recorder(
		[
			ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': first})]),
			ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': first})]),
		]
	)
	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=model):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	retry = [p.content for p in seen[1][0][-1].parts if getattr(p, 'outcome', None) == 'retried']
	assert retry and ('placeholder' in retry[0] or 'leads.csv' in retry[0])
	assert (len(seen), result.status, result.output) == (2, 'completed', first)  # second identical finish accepted


async def test_existing_file_link_and_short_answer_pass(daemon, tmp_path):
	(tmp_path / 'out.csv').write_text('a\n1\n')
	for answer in ['7', 'See [out.csv](out.csv), `out.csv` and [site](https://example.com)']:
		result, seen = await go(daemon, tmp_path, [('finish', {'success': True, 'result': answer})])
		assert (len(seen), result.output) == (1, answer)


async def test_partial_result_is_accepted_without_a_continue_turn(daemon, tmp_path):
	# The early-partial guard was removed: bench 1106 showed it fired in 57/120 runs, +30 steps/task, no score gain (bu-pi has none).
	first = 'Partial: only 5 of 37 listings checked.'
	model, seen = _choice_recorder([ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': first})])])
	agent, session = build_agent(), Session(repl=Repl(tmp_path, daemon))
	try:
		with agent.override(model=model):
			result = await run(agent, 'task', session, 'gpt-6-luna')
	finally:
		await session.repl.close()
	assert (len(seen), result.output) == (1, first)


async def test_screenshot_is_jpeg(daemon, tmp_path):
	# bu-pi parity: JPEG q70; v1b's 60s full-PNG captures timed out on 48 of 280 Hard screenshot() calls.
	result, seen = await go(
		daemon,
		tmp_path,
		[
			('python', {'code': "new_tab('data:text/html,<h1>hi</h1>')\nwait_for_load()\np = screenshot()\np"}),
			('finish_from_repl', {'success': True, 'expression': 'p'}),
		],
	)
	out = [p for p in seen[1].parts if isinstance(p, ToolReturnPart)][0].content
	assert result.status == 'completed', out
	assert result.output.endswith('.jpg') and Path(result.output).read_bytes()[:2] == b'\xff\xd8'
	assert any(getattr(c, 'media_type', '') == 'image/jpeg' for c in out)


async def test_screenshot_of_a_hidden_tab_succeeds(daemon, tmp_path):
	"""new_tab()/switch_tab() never activate a tab, and Linux headless sometimes renders no frames for a hidden one
	(CI hung 60s on it). screenshot() and raw cdp('Page.captureScreenshot') of a hidden tab both return an image:
	whether the capture works directly or needs the activate-after-a-short-try path depends on the Chrome build, so
	only success is asserted here; when activation happens is pinned by the stubbed unit tests above."""
	from browser_use.repl.session import Repl

	repl = Repl(tmp_path, daemon)
	try:
		code = (
			"a = new_tab('data:text/html,<h1>A</h1>'); wait_for_load()\n"
			"b = new_tab('data:text/html,<h1>B</h1>'); wait_for_load()\n"
			"vis = lambda: js('document.visibilityState')\n"
			'switch_tab(a); v = [vis()]; p = screenshot(); v.append(vis())\n'
			"switch_tab(b); v.append(vis()); r = cdp('Page.captureScreenshot'); v.append(vis())\n"
			"print(*v, p.endswith('.jpg'), bool(r.get('data')))"
		)
		r = await repl.call('exec', code, 90)
	finally:
		await repl.close()
	assert r['error'] is None, r
	out = r['output'].split()
	assert out[0] == out[2] == 'hidden' and out[4:] == ['True', 'True'], r['output']


async def test_tabs_of_a_browser_we_own_are_visible_so_scroll_and_keys_work(daemon, tmp_path):
	"""C09: the daemon's first tab and every new_tab() were hidden background tabs. A hidden tab never paints, so scroll()
	timed out and keys and clicks were dropped until a screenshot. In a browser we launched or were given, the agent's
	tab is the visible one (as in 0.x), and press_key() sends no nativeVirtualKeyCode (on macOS browser-harness's Windows
	code opened chrome://settings/help on every printable key)."""
	from browser_use.repl.session import Repl

	repl = Repl(tmp_path, {**daemon, 'BU_OWN_BROWSER': '1'})
	try:
		code = (
			"v = [js('document.visibilityState')]\n"
			"new_tab('data:text/html,<input id=i autofocus><div style=height:5000px></div>'); wait_for_load()\n"
			"v.append(js('document.visibilityState'))\n"
			"js('document.getElementById(\"i\").focus()'); press_key('a'); press_key('b')\n"
			'scroll(100, 100, dy=600); time.sleep(0.5)\n'
			"print(*v, js('document.getElementById(\"i\").value'), js('scrollY') > 0,"
			" any(t['url'].startswith('chrome://settings') for t in list_tabs()))"
		)
		r = await repl.call('exec', code, 90)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert r['output'].split() == ['visible', 'visible', 'ab', 'True', 'False'], r['output']


async def test_a_browser_that_cannot_be_reattached_ends_the_cells(tmp_path):
	"""C04: after the browser died and could not be reattached, the model kept running cells and went looking for another
	browser: it reattached browser-harness to another run's Chrome and drove it. The next turn is now delivery-only: no
	more cells, and finish_from_repl still delivers what the REPL has."""
	from browser_use.agent.loop import DELIVER_NOW, NOT_RUN

	async def reattach():
		raise RuntimeError('The browser is gone: its browser-harness daemon stopped and could not reattach')

	lost = 'found = [1]\nfrom browser_use.exceptions import BrowserConnectionLost\nraise BrowserConnectionLost()'
	model, seen = script(
		('python', {'code': lost}),
		('python', {'code': "open('hijack.txt', 'w').write('ran')"}),
		('finish_from_repl', {'expression': 'json.dumps(found)', 'success': False}),
	)
	session = Session(repl=Repl(tmp_path, reattach=reattach))
	try:
		result = await run(build_agent(model), 'task', session, 'm')
	finally:
		await session.repl.close()
	assert (result.status, result.output) == ('completed', '[1]'), result.error
	assert 'Finish with what you have' in str(seen[1][-1]) and DELIVER_NOW in str(seen[1][-1])
	assert NOT_RUN in str(seen[2][-1]) and not (tmp_path / 'hijack.txt').exists()
	assert session.budget_hit == 'browser_gone'


async def test_unknown_tool_names_are_retried_without_ending_the_run(tmp_path):
	"""Matrix v2, DeepSeek bub2-007: a second call to the made-up tool 'code' ended the run at step 140 (Pydantic AI
	never resets the retry count of a name that does not exist). bu-pi answers "Tool code not found" and goes on."""
	model, seen = script(
		('code', {'src': '1'}),
		('python', {'code': 'x = 1'}),
		('code', {'src': '2'}),
		('code', {}),
		('finish', {'result': 'ok', 'success': True}),
	)
	result = await run(build_agent(model), 'task', Session(repl=FakeRepl(tmp_path)), 'function:x')
	assert result.status == 'completed' and result.output == 'ok', result.error
	assert "Unknown tool name: 'code'" in str(seen[3][-1].parts[0].content)


async def test_repeated_bad_tool_arguments_do_not_end_the_run(tmp_path):
	"""python and custom Tools had one retry of their own: two rejected calls in a row (a cell truncated at the output
	cap, a JSON slip, a wrong key) ended the run with UnexpectedModelBehavior / IncompleteToolCall."""
	from browser_use import Tools

	tools = Tools()

	@tools.action('Look up a price')
	def price(sku: str) -> str:
		return f'price of {sku}: 7'

	truncated = '{"code": "rows = []\\nfor u in urls:\\n    js('
	turns = [('python', truncated), ('python', {'cmd': 'print(1)'}), ('price', {}), ('price', '{"sku": ')]
	requests = []

	def fn(messages, info: AgentInfo):
		requests.append(messages)
		if len(requests) <= len(turns):
			name, args = turns[len(requests) - 1]
			return ModelResponse(parts=[ToolCallPart(name, args)], finish_reason='length' if args == truncated else 'tool_call')
		return ModelResponse(parts=[ToolCallPart('finish', {'result': 'ok', 'success': True})])

	agent = build_agent(FunctionModel(fn), tools=tools.functions)
	result = await run(agent, 'task', Session(repl=FakeRepl(tmp_path)), 'function:x')
	assert (result.status, result.output, result.error) == ('completed', 'ok', None)
	assert len(requests) == 5


async def test_a_custom_tool_never_runs_with_a_secret_placeholder_for_a_value(tmp_path):
	"""0.x replaced <secret>name</secret> in action arguments with the value. 1.0 passed the placeholder through: the
	tool sent '<secret>pw</secret>' as the password and the run reported completed. Now it is refused, loudly."""
	from browser_use import Tools

	tools, got = Tools(), []

	@tools.action('Log in to the internal API')
	def api_login(password: str) -> str:
		got.append(password)
		return 'ok'

	model, seen = script(
		('api_login', {'password': '<secret>pw</secret>'}),
		('api_login', {'password': 'x <secret:pw> y'}),
		('api_login', {'password': '<secret>not-a-secret-name</secret>'}),
		('finish', {'result': 'done', 'success': True}),
	)
	session = Session(repl=FakeRepl(tmp_path, {'pw': 'hunter2-value'}))
	result = await run(build_agent(model, tools=tools.functions), 'task', session, 'function:x')
	assert result.status == 'completed' and got == ['<secret>not-a-secret-name</secret>']
	for request in seen[1:3]:
		assert 'api_login was not run: custom tools do not receive secret values' in str(request[-1].parts[0].content)


async def test_a_stalled_model_request_still_leaves_the_delivery_turn(tmp_path):
	"""A provider that accepts a request and never answers held the run until its timeout: status=timeout, output ''.
	Each request now has a deadline (bu-pi deadlineStream, 300 s) that ends at the delivery turn's start."""
	import asyncio

	requests = []

	async def fn(messages, info: AgentInfo):
		requests.append(info.model_settings)
		if len(requests) == 1:
			return ModelResponse(parts=[ToolCallPart('python', {'code': 'x = 1'})])
		if len(requests) == 2:
			await asyncio.sleep(3600)  # accepted, never answered
		return ModelResponse(parts=[ToolCallPart('finish', {'result': 'delivered', 'success': True})])

	session = Session(repl=FakeRepl(tmp_path), timeout_s=6)  # the delivery turn starts at 3 s
	result = await run(build_agent(FunctionModel(fn)), 'task', session, 'function:x')
	assert (result.status, result.output, session.budget_hit) == ('completed', 'delivered', 'timeout'), result.error
	assert len(requests) == 3 and requests[2]['tool_choice'] == ['finish_from_repl', 'finish']
	assert 2 < requests[1]['request_timeout'] <= 3 and requests[0]['request_timeout'] <= 3


async def test_a_tool_call_written_as_text_is_not_the_answer(tmp_path):
	"""Matrix v2, Grok bub2-020: the final answer was '<tool_call>{"name": "finish_from_repl", ...}</tool_call>' as text.
	It ran nothing; it now gets the delivery repair turn (bu-pi's, for any text ending) and the real call delivers."""
	markup = '<tool_call>{"name": "finish_from_repl", "arguments": {"expression": "result", "success": true}}</tool_call>'
	requests = []

	def fn(messages, info: AgentInfo):
		requests.append(messages)
		if len(requests) == 1:
			return ModelResponse(parts=[TextPart(markup)])
		return ModelResponse(parts=[ToolCallPart('finish', {'result': 'the answer', 'success': True})])

	result = await run(build_agent(FunctionModel(fn)), 'task', Session(repl=FakeRepl(tmp_path)), 'function:x')
	assert result.status == 'completed' and result.output == 'the answer' and len(requests) == 2, result.error
	assert 'wrote a tool call as text' in str(requests[1][-1].parts)
