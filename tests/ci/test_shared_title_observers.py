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
  return {observers: globalThis.observerCount, callbacks: globalThis.callbackCount};
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
			assert counts == {'observers': 1, 'callbacks': 30}, counts

		for worker in range(2):
			repl = Repl(tmp_path / str(worker), env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
			try:
				await measure(repl)
				if worker == 0:  # a new document needs a new observer, while a new worker on that document does not
					await measure(repl, "goto_url('data:text/html,<title>Next</title><body>after</body>'); wait_for_load()\n")
			finally:
				await repl.close()
	finally:
		_shutdown_daemon(name)
