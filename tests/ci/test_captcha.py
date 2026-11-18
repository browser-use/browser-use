"""Browser Use Cloud captcha solver: solve_captcha() and the cell notice, against a fake CDP endpoint that speaks our
cloud browser's BrowserUse.* methods and events. No browser, no cloud."""

import asyncio
import json
import os
import threading
import time

import pytest

from browser_use.repl import Repl
from browser_use.repl.captcha import FINISHED, STARTED, Captcha


class FakeCloudBrowser:
	"""A CDP websocket with one page that answers BrowserUse.* like our cloud browser and broadcasts its events.
	on_enable: events sent (with their delays) when the agent turns the solver on."""

	def __init__(self, solver: bool = True):
		self.solver, self.enabled, self.calls = solver, True, []
		self.on_enable: list[tuple[float, str, dict]] = []
		self.clients: set = set()
		self.loop = asyncio.new_event_loop()
		started = threading.Event()
		threading.Thread(target=self._run, args=(started,), daemon=True).start()
		started.wait(10)

	def _run(self, started: threading.Event) -> None:
		from websockets.asyncio.server import serve

		async def main():
			self.stopped = asyncio.Event()
			async with serve(self._client, '127.0.0.1', 0, max_size=None) as server:
				self.ws = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/devtools/browser/fake'
				started.set()
				await self.stopped.wait()

		asyncio.set_event_loop(self.loop)
		self.loop.run_until_complete(main())

	async def _client(self, ws) -> None:
		self.clients.add(ws)
		try:
			async for raw in ws:
				msg = json.loads(raw)
				method, params = msg.get('method', ''), msg.get('params') or {}
				reply: dict = {'id': msg['id'], 'result': self._answer(method, params)}
				if method.startswith('BrowserUse.'):
					self.calls.append((method, params))
					if not self.solver:
						reply = {'id': msg['id'], 'error': {'code': -32601, 'message': f"'{method}' wasn't found"}}
				if msg.get('sessionId'):
					reply['sessionId'] = msg['sessionId']
				await ws.send(json.dumps(reply))
				if method == 'BrowserUse.setCaptchaSolverEnabled' and params.get('enabled') and self.solver:
					for delay, event, data in self.on_enable:
						self.loop.call_later(delay, self._broadcast, event, data)
		finally:
			self.clients.discard(ws)

	def _answer(self, method: str, params: dict) -> dict:
		page = {'targetId': 'T1', 'type': 'page', 'url': 'https://example.com/', 'title': 'Example', 'attached': True}
		if method == 'Target.getTargets':
			return {'targetInfos': [page]}
		if method == 'Target.getTargetInfo':
			return {'targetInfo': page}
		if method == 'Target.createTarget':
			return {'targetId': 'T1'}
		if method == 'Target.attachToTarget':
			return {'sessionId': 'S1'}
		if method == 'BrowserUse.getCaptchaSolverEnabled':
			return {'enabled': self.enabled}
		if method == 'BrowserUse.setCaptchaSolverEnabled':
			self.enabled = params['enabled']
			return {'enabled': self.enabled}
		return {}

	def _broadcast(self, method: str, params: dict, session: str | None = None) -> None:
		msg = json.dumps({'method': method, 'params': params, **({'sessionId': session} if session else {})})
		for ws in list(self.clients):
			asyncio.ensure_future(ws.send(msg))

	def emit(self, method: str, params: dict, session: str | None = None) -> None:
		self.loop.call_soon_threadsafe(self._broadcast, method, params, session)

	def close(self) -> None:
		self.loop.call_soon_threadsafe(self.stopped.set)


def started(vendor='recaptcha'):
	return STARTED, {'targetId': 'T1', 'vendor': vendor, 'url': 'https://example.com/', 'startedAt': 1}


def finished(success=True, ms=3000):
	return FINISHED, {
		'targetId': 'T1',
		'vendor': 'recaptcha',
		'url': 'https://example.com/',
		'durationMs': ms,
		'finishedAt': 2,
		'success': success,
	}


@pytest.fixture
def cloud():
	"""A fake cloud browser behind a named browser-harness daemon: (fake, REPL env) for a cloud-browser worker."""
	from browser_harness import admin

	from browser_use.browser.browser import _shutdown_daemon

	fake = FakeCloudBrowser()
	name = f'bucaptcha{os.getpid()}{fake.ws.split(":")[2].split("/")[0]}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': fake.ws, 'BH_TAB_MARKER': '0'})
	try:
		yield fake, {'BU_NAME': name, 'BU_REMOTE_BROWSER': '1'}
	finally:
		_shutdown_daemon(name)
		fake.close()


def fake_captcha(enabled: bool, error: Exception | None = None):
	"""A Captcha whose cdp records calls; feed() queues events that pump() delivers one batch per call."""
	calls: list = []
	state = {'enabled': enabled}

	def cdp(method, **params):
		calls.append((method, params))
		if error:
			raise error
		if method == 'BrowserUse.setCaptchaSolverEnabled':
			state['enabled'] = params['enabled']
		return {'enabled': state['enabled']}

	c = Captcha(cdp)
	batches: list[list[tuple[str, dict]]] = []
	c.pump = lambda: [c.observe({'method': m, 'params': p}) for m, p in (batches.pop(0) if batches else [])]
	return c, calls, batches


def test_solve_waits_for_a_running_solve_and_never_turns_an_enabled_solver_off():
	c, calls, batches = fake_captcha(enabled=True)
	batches += [[started()], [], [finished(success=True)]]
	r = c.solve(start_timeout=5, timeout=5)
	assert (r['solved'], r['detail']) == (True, 'solved')
	assert calls == [('BrowserUse.getCaptchaSolverEnabled', {})]  # on by default: left on, never toggled

	batches += [[started()], [finished(success=False)]]
	assert c.solve(start_timeout=5, timeout=5)['detail'] == 'the solver failed'


def test_solve_turns_an_off_solver_on_and_back_off_unless_it_is_still_solving():
	c, calls, batches = fake_captcha(enabled=False)
	r = c.solve(start_timeout=0.3, timeout=0.3)
	assert (r['solved'], r['detail']) == (False, 'the solver found no captcha on the page')
	assert [p for m, p in calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [{'enabled': True}, {'enabled': False}]

	calls.clear()
	batches.append([started()])
	r = c.solve(start_timeout=0.3, timeout=0.5)
	assert (r['detail'], r['next']) == ('still solving', 'call solve_captcha() again')
	assert [p for m, p in calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [{'enabled': True}]  # left on

	calls.clear()
	batches.append([finished(success=True)])  # the next call picks up the solve that is still running
	assert c.solve(start_timeout=0.3, timeout=5)['detail'] == 'solved'
	# H11: then it goes off again; it stayed on for the rest of the session
	assert [p for m, p in calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [{'enabled': False}]


def test_a_solver_left_on_for_a_running_solve_goes_off_when_it_ends_even_after_a_worker_restart(tmp_path):
	"""Review: after 'still solving', the solver stayed on until the agent called solve_captcha() again (never, if it
	moved on), and a worker restarted by a cell timeout forgot that solve() had turned it on, so it stayed on."""
	c, calls, batches = fake_captcha(enabled=False)
	c.path = tmp_path / 'captcha.json'
	batches.append([started()])
	assert c.solve(start_timeout=0.3, timeout=0.3)['detail'] == 'still solving'
	calls.clear()
	c.observe(dict(zip(('method', 'params'), finished(success=True))))  # the agent moved on; the solve ends
	assert [p for m, p in calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [{'enabled': False}]

	batches.append([started()])
	assert c.solve(start_timeout=0.3, timeout=0.3)['detail'] == 'still solving'
	restarted = Captcha(c.cdp, c.path)  # the next cell timed out: a new worker reads the saved state
	calls.clear()
	restarted.observe(dict(zip(('method', 'params'), finished(success=True))))
	assert [p for m, p in calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [{'enabled': False}]


def test_solve_never_turns_on_a_solver_the_user_turned_off():
	"""H11: with Browser(captcha_solver=False), solve_captcha() turned the solver on anyway."""
	c, calls, batches = fake_captcha(enabled=False)
	c.off = True
	batches.append([started()])
	r = c.solve(start_timeout=0.3, timeout=0.3)
	assert (r['solved'], r['detail']) == (False, r['detail']) and 'captcha_solver=False' in r['detail']
	assert calls == []


def test_solve_on_a_browser_without_a_solver_is_unavailable():
	err = RuntimeError("{'code': -32601, 'message': \"'BrowserUse.getCaptchaSolverEnabled' wasn't found\"}")
	c, calls, _ = fake_captcha(enabled=False, error=err)
	r = c.solve()
	assert r['solved'] is False and r['detail'].startswith('solver unavailable: this browser has no captcha solver')
	assert r['seconds'] < 1 and len(calls) == 1


def test_report_shows_a_running_solve_and_each_end_once():
	c, _, batches = fake_captcha(enabled=True)
	assert c.report() == ''
	c.observe(dict(zip(('method', 'params'), started('hcaptcha'))))
	notice = c.report()
	assert 'solving hcaptcha on https://example.com/' in notice and 'solve_captcha()' in notice and 'reload' in notice
	c.observe(dict(zip(('method', 'params'), finished(success=True, ms=12_400))))
	assert c.report() == '[captcha solver: solved recaptcha in 12s]'
	assert c.report() == ''
	# A solve that ended between cells is solve_captcha()'s answer, not a 20 s wait for a new one.
	c.observe(dict(zip(('method', 'params'), finished(success=False))))
	assert c.solve(start_timeout=5)['detail'] == 'the solver failed'


def test_solve_after_the_notice_showed_the_end_returns_that_result_at_once():
	"""captcha finding 2: the notice said '[captcha solver: solved recaptcha in 3s]', the model called solve_captcha() as
	told, waited 20 s and got 'the solver found no captcha on the page'."""
	c, _, _ = fake_captcha(enabled=True)
	c.observe(dict(zip(('method', 'params'), started())))
	c.observe(dict(zip(('method', 'params'), finished(success=True))))
	assert c.report() == '[captcha solver: solved recaptcha in 3s]'
	r = c.solve(start_timeout=5)
	assert (r['solved'], r['detail']) == (True, 'solved') and r['seconds'] < 1
	assert c.report() == ''  # a later cell without captcha output: that solve is no longer the answer
	assert c.solve(start_timeout=0.3)['detail'] == 'the solver found no captcha on the page'


def test_solve_waits_for_every_tab_and_reports_a_failure_over_a_later_success():
	"""A solve that finishes on one tab is not the answer while another tab is still solving (bu-pi waits for all)."""
	c, _, batches = fake_captcha(enabled=True)
	t2 = {'targetId': 'T2', 'vendor': 'hcaptcha', 'url': 'https://example.org/'}
	batches += [[started(), (STARTED, t2)], [finished(success=True)]]
	r = c.solve(start_timeout=5, timeout=0.5)
	assert (r['solved'], r['detail']) == (False, 'still solving') and list(c.active) == ['T2']

	batches += [[(FINISHED, {**t2, 'success': False, 'durationMs': 1000})]]
	assert c.solve(start_timeout=5, timeout=5)['detail'] == 'the solver failed'

	batches += [[started(), (STARTED, t2)], [(FINISHED, {**t2, 'success': False})], [finished(success=True)]]
	r = c.solve(start_timeout=5, timeout=5)  # T2 failed, T1 then solved: the failure is the answer
	assert (r['solved'], r['detail']) == (False, 'the solver failed')


def test_a_solve_whose_finish_never_comes_is_closed_as_lost():
	"""A tab closed mid-solve or a missed finished event: the solve is not 'running' forever (bu-pi lostAfterMs)."""
	c, _, _ = fake_captcha(enabled=True)
	c.observe(dict(zip(('method', 'params'), started())))
	c.active['T1']['_t'] -= 151  # past the solver's own 120 s limit plus slack (bu-pi: 150 s)
	r = c.solve(start_timeout=1, timeout=1)
	assert (r['solved'], r['detail']) == (False, 'no result from the solver after 150s') and r['seconds'] < 0.5
	assert c.active == {}
	assert c.report().startswith('[captcha solver: no result for recaptcha after 151s')

	c.observe(dict(zip(('method', 'params'), started())))
	c.active['T1']['_t'] -= 151
	notice = c.report()  # the cell notice stops telling the agent to wait
	assert 'no result for recaptcha' in notice and 'solving' not in notice and c.report() == ''


async def test_solve_captcha_through_the_daemon(cloud, tmp_path):
	fake, env = cloud
	fake.enabled = False  # ultrafast-style: off until asked
	fake.on_enable = [(0.3, *started()), (0.8, *finished(success=True))]
	repl = Repl(tmp_path, env)
	try:
		r = await repl.call('exec', 'solve_captcha()', 30)
		assert r['error'] is None, r
		assert "'solved': True" in r['output'] and "'detail': 'solved'" in r['output']
		assert '[captcha solver: solved recaptcha in 3s]' in r['output']
		assert [p for m, p in fake.calls if m == 'BrowserUse.setCaptchaSolverEnabled'] == [
			{'enabled': True},
			{'enabled': False},
		]
		# telemetry: the call and the solve, read by the worker's event reader, are counted (names only)
		assert r['stats']['helpers'].get('solve_captcha') == 1, r['stats']
		assert r['stats']['events'] == {'captcha_started': 1, 'captcha_solved': 1}, r['stats']
	finally:
		await repl.close()


async def test_a_solve_that_starts_between_cells_is_in_the_next_output_despite_a_busy_page(cloud, tmp_path):
	"""The daemon keeps only its last 500 events; the worker reads them continuously, so 2000 Network events after
	the start never hide it."""
	fake, env = cloud
	repl = Repl(tmp_path, env)
	try:
		assert (await repl.call('exec', '1', 30))['error'] is None  # worker up, reading events
		fake.emit(*started())
		for i in range(2000):
			fake.emit('Network.dataReceived', {'requestId': str(i), 'dataLength': 1}, 'S1')
			if i % 100 == 0:
				await asyncio.sleep(0.05)
		await asyncio.sleep(0.5)
		r = await repl.call('exec', 'events = drain_events()\nlen(events)', 30)
		assert '[captcha solver: solving recaptcha on https://example.com/' in r['output'], r['output']
		assert r['output'].split('\n')[0] == '500'  # the agent still gets the last 500, as from the daemon
		fake.emit(*finished(success=True))
		await asyncio.sleep(0.5)
		r = await repl.call('exec', 'solve_captcha(start_timeout=1)', 30)
		assert "'detail': 'solved'" in r['output'] and '[captcha solver: solved recaptcha in 3s]' in r['output']
	finally:
		await repl.close()


async def test_solve_captcha_on_another_browser_is_unavailable(cloud, tmp_path):
	fake, env = cloud
	fake.solver = False
	repl = Repl(tmp_path, env)
	try:
		t = time.monotonic()
		r = await repl.call('exec', 'solve_captcha()', 30)
		assert 'solver unavailable: this browser has no captcha solver' in r['output'], r
		assert time.monotonic() - t < 10
	finally:
		await repl.close()


async def test_a_worker_restarted_by_a_cell_timeout_still_knows_the_running_solve(cloud, tmp_path):
	"""captcha finding 1: a CellTimeout while solve_captcha() waited killed the worker; the new one had forgotten the
	running solve, showed no notice and answered the next solve_captcha() with 'found no captcha'."""
	fake, env = cloud
	repl = Repl(tmp_path, env)
	try:
		assert (await repl.call('exec', '1', 30))['error'] is None  # worker up, reading events
		fake.emit(*started())
		await asyncio.sleep(0.5)
		r = await repl.call('exec', 'solve_captcha()', 3)  # waits for the finish, past the cell deadline
		assert 'timed out' in (r['error'] or '') + r['output'], r
		r = await repl.call('exec', '1', 30)  # a new worker
		assert '[captcha solver: solving recaptcha on https://example.com/' in r['output'], r['output']
		fake.emit(*finished(success=True))
		await asyncio.sleep(0.5)
		r = await repl.call('exec', 'solve_captcha(start_timeout=1)', 30)
		assert "'detail': 'solved'" in r['output'], r['output']
	finally:
		await repl.close()
	Repl(tmp_path, env)  # a new Repl is a new browser session: it starts without the saved state
	assert not (tmp_path / '.browser-use' / 'captcha.json').exists()


async def test_captcha_solver_false_turns_the_cloud_solver_off_at_start(monkeypatch):
	"""captcha finding 6: 1.0 had no knob for the cloud solver; Browser(captcha_solver=False) was a generic TypeError and
	MIGRATING.md said to delete it."""
	from browser_use import Agent, Browser
	from browser_use.agent.prompt import CAPTCHA_PROMPT, NO_CAPTCHA_PROMPT
	from browser_use.browser import browser as browser_mod

	fake = FakeCloudBrowser()

	async def start_cloud(self):
		self.id = 'b1'
		return fake.ws

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(Browser, '_start_cloud', start_cloud)
	monkeypatch.setattr(browser_mod, '_cloud', lambda path, method='GET', body=None: {})
	try:
		for solver in (True, False):
			fake.calls.clear()
			browser = Browser(captcha_solver=solver)
			env = await browser.start()
			await browser.stop()
			assert fake.calls == ([] if solver else [('BrowserUse.setCaptchaSolverEnabled', {'enabled': False})])
			assert ('BU_CAPTCHA_SOLVER' in env) is not solver  # the worker's solve_captcha() keeps it off (H11)
		assert fake.enabled is False
	finally:
		browser_mod._LIVE.clear()
		fake.close()

	def instructions(browser) -> str:
		agent = Agent('t', 'test', browser=browser)
		agent._build()
		return '\n'.join(i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str))

	assert CAPTCHA_PROMPT in instructions(Browser()) and NO_CAPTCHA_PROMPT not in instructions(Browser())
	off = instructions(Browser(captcha_solver=False))
	assert NO_CAPTCHA_PROMPT in off and 'solve_captcha' not in off
	with pytest.raises(ValueError, match=r'only Browser\(\) \(a cloud browser\) has a captcha solver'):
		Browser('chromium', captcha_solver=False)
