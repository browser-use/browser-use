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

	batches.append([finished(success=True)])  # the next call picks up the solve that is still running
	assert c.solve(start_timeout=0.3, timeout=5)['detail'] == 'solved'


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
