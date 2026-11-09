"""Shared Chrome's title observer must not multiply when a tab is selected again."""

import json
import os

from browser_harness import admin

from browser_use.browser.browser import _daemon_cdp, _daemon_request, _shutdown_daemon
from browser_use.repl import Repl


async def test_selecting_a_shared_tab_keeps_one_title_observer(chrome, tmp_path):
	name = f'butestobservers{os.getpid()}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws'], 'BH_TAB_MARKER': '1'})
	cdp = lambda method, **params: _daemon_cdp(name, method, **params)
	try:
		tab = cdp('Target.createTarget', url='data:text/html,<title>Fixture</title><body>before</body>')['targetId']
		sid = cdp('Target.attachToTarget', targetId=tab, flatten=True)['sessionId']
		_daemon_request(name, {'meta': 'set_session', 'session_id': sid, 'target_id': tab})
		# Instrument only the isolated world used by the title script. Page JS and browser-harness keep their
		# native MutationObserver. This script also runs before the title scripts on a later navigation.
		cdp(
			'Page.addScriptToEvaluateOnNewDocument',
			worldName='browser-use-unmark',
			runImmediately=True,
			source="""
globalThis.observerCount = 0;
globalThis.callbackCount = 0;
globalThis.scriptRuns = 0;
let unmarked = false;
Object.defineProperty(globalThis, '__browserUseUnmarkTitle', {
  get() { globalThis.scriptRuns++; return unmarked; },
  set(value) { unmarked = value; }
});
const NativeObserver = MutationObserver;
globalThis.MutationObserver = class extends NativeObserver {
  constructor(callback) {
    globalThis.observerCount++;
    super((records, observer) => { globalThis.callbackCount++; callback(records, observer); });
  }
};""",
		)
		measure_js = """(async () => {
  globalThis.callbackCount = 0;
  for (let i = 0; i < 30; i++) {
    document.body.textContent = String(i);
    await Promise.resolve();
  }
  return {observers: globalThis.observerCount, callbacks: globalThis.callbackCount, scripts: globalThis.scriptRuns};
})()"""
		code = f"""import json
for _ in range(20):
    switch_tab({tab!r})
frame = cdp('Page.getFrameTree')['frameTree']['frame']['id']
world = cdp('Page.createIsolatedWorld', frameId=frame, worldName='browser-use-unmark')['executionContextId']
counts = cdp('Runtime.evaluate', contextId=world, returnByValue=True, awaitPromise=True, expression={measure_js!r})['result']['value']
print(json.dumps(counts))"""

		async def measure(repl, prefix=''):
			r = await repl.call('exec', prefix + code, 60)
			assert r['error'] is None, r
			counts = json.loads(r['output'])
			assert counts == {'observers': 1, 'callbacks': 30, 'scripts': 1}, counts

		async def navigate(repl, title, prefix=''):
			r = await repl.call(
				'exec',
				prefix
				+ f"""goto_url('data:text/html,<title>{title}</title><body>after</body>'); wait_for_load()
import time
deadline = time.time() + 2
while time.time() < deadline and not page_info()['title'].startswith('\\U0001F434'):
    time.sleep(0.05)
print(page_info()['title'])""",
				30,
			)
			assert r['error'] is None and r['output'].strip() == title, r

		for worker in range(2):
			repl = Repl(tmp_path / str(worker), env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
			try:
				await measure(repl)
				if worker == 0:  # a new document needs a new observer, while a new worker on that document does not
					await measure(
						repl,
						f"""import browser_harness.helpers as _helpers
owner_session = cdp('Runtime.evaluate', contextId=world, expression='globalThis.__browserUseUnmarkSession', returnByValue=True)['result']['value']
original_send = _helpers._send
probe_pending = True
def fail_one_probe(req, *args, **kwargs):
    global probe_pending
    if probe_pending and req.get('method') == 'Page.getFrameTree' and req.get('session_id') == owner_session:
        probe_pending = False
        raise TimeoutError('synthetic session probe timeout')
    return original_send(req, *args, **kwargs)
_helpers._send = fail_one_probe
try:
    switch_tab({tab!r})
finally:
    _helpers._send = original_send
assert not probe_pending
""",
					)
					await measure(repl, "goto_url('data:text/html,<title>Next</title><body>after</body>'); wait_for_load()\n")
				else:
					# A still-open page can lose the session that owns its registration. The replacement must survive
					# the next navigation, when its old document's observer is gone.
					await navigate(
						repl,
						'Detached',
						f"""frame = cdp('Page.getFrameTree')['frameTree']['frame']['id']
world = cdp('Page.createIsolatedWorld', frameId=frame, worldName='browser-use-unmark')['executionContextId']
owner = cdp('Runtime.evaluate', contextId=world, expression='globalThis.__browserUseUnmarkSession', returnByValue=True)['result']['value']
cdp('Target.detachFromTarget', sessionId=owner)
switch_tab({tab!r})
""",
					)
			finally:
				await repl.close()

		# A new daemon has no sessions from the previous connection, while the page and its isolated world survive.
		_shutdown_daemon(name)
		admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws'], 'BH_TAB_MARKER': '1'})
		sid = cdp('Target.attachToTarget', targetId=tab, flatten=True)['sessionId']
		_daemon_request(name, {'meta': 'set_session', 'session_id': sid, 'target_id': tab})
		repl = Repl(tmp_path / 'daemon-restart', env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
		try:
			await navigate(repl, 'Restarted')
		finally:
			await repl.close()
	finally:
		_shutdown_daemon(name)
