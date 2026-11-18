"""wait_for_network_idle() for the REPL, ported from browser-harness PR #982 (browser-4).

DELETE this module and its one use in worker.py once browser-harness >= 0.1.14 (with #982) is pinned.

browser-harness 0.1.13's helper waits for two kinds of request that start on the tab's CDP session but finish elsewhere,
so it ran to its 10 s cap on any page with a Web Worker or an out-of-process (cross-site: ad, captcha, chat) iframe:
- a worker's script: CDP sends it with loaderId "" ("fetched from worker"); it finishes on the worker's target, or never
  if the worker stops first. Not waited for.
- an out-of-process iframe's document: it finishes on the iframe's own target. #982 has the daemon auto-attach child
  targets and drops the request when one attaches; 0.1.13's daemon sends every Target.* call browser-wide, so this
  cannot. The tab's session reports the same moment as Page.frameDetached with reason 'swap' (the frame moved to
  another process): its requests are dropped, and new ones of that frame are not waited for until Page.frameAttached
  says it is back in process, when the tab reports its requests again.
"""

import time


def wait_for_network_idle(timeout=10.0, idle_ms=500):
	"""Wait until all in-flight requests finish and no Network.* events arrive for idle_ms ms.

	Useful after form submits, SPA route transitions, and any action that triggers XHR/fetch without a visible DOM
	change. Returns True if idle window reached, False on timeout. Workers' scripts and out-of-process iframes'
	documents, which finish on their own targets, are not waited for."""
	from browser_harness import helpers

	deadline = time.time() + timeout
	last_activity = time.time()
	inflight: dict[str, str | None] = {}  # requestId -> frameId
	remote: set[str] = set()  # frames of the tab now in another process (out-of-process iframes)
	active_session = helpers._send({'meta': 'session'}).get('session_id')
	while time.time() < deadline:
		for e in helpers.drain_events():
			if e.get('session_id') != active_session:
				continue
			method = e.get('method', '')
			params = e.get('params', {})
			if method == 'Network.requestWillBeSent':
				if params.get('loaderId') != '' and params.get('frameId') not in remote:
					inflight[params.get('requestId')] = params.get('frameId')
				last_activity = time.time()
			elif method in ('Network.loadingFinished', 'Network.loadingFailed'):
				inflight.pop(params.get('requestId'), None)
				last_activity = time.time()
			elif method.startswith('Network.'):
				last_activity = time.time()
			elif method == 'Page.frameDetached' and params.get('reason') == 'swap':
				remote.add(params.get('frameId'))
				inflight = {r: f for r, f in inflight.items() if f != params.get('frameId')}
			elif method == 'Page.frameAttached':
				remote.discard(params.get('frameId'))
		if not inflight and (time.time() - last_activity) * 1000 >= idle_ms:
			return True
		time.sleep(0.1)
	return False
