"""Shared Chrome's title observer must not multiply when a tab is selected again."""

import json
import os

import pytest
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
			mark_title_js = """(async () => {
  document.title = '\\u{1F434} ' + document.title;
  await Promise.resolve();
  return document.title;
})()"""
			r = await repl.call(
				'exec',
				prefix
				+ f"""goto_url('data:text/html,<title>{title}</title><body>after</body>'); wait_for_load()
print(cdp('Runtime.evaluate', expression={mark_title_js!r}, awaitPromise=True, returnByValue=True)['result']['value'])""",
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
		admin.restart_daemon(name)  # wait for the old endpoint to close before starting its replacement
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


@pytest.mark.parametrize('lost', ['context', 'frame'])
async def test_shared_title_discovery_recovers_from_navigation_context_loss(chrome, tmp_path, lost):
	name = f'butesttitleloss{os.getpid()}{lost}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws'], 'BH_TAB_MARKER': '1'})
	repl = Repl(tmp_path, env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
	mark_title_js = """(async () => {
  document.title = '\\u{1F434} Recovered';
  await Promise.resolve();
  return document.title;
})()"""
	try:
		r = await repl.call(
			'exec',
			f"""import browser_harness.helpers as _helpers
tab = cdp('Target.createTarget', url='about:blank')['targetId']
original_send = _helpers._send
lost_error = None
def lose_one_context(req, *args, **kwargs):
    global lost_error
    method = 'Runtime.evaluate' if {lost!r} == 'context' else 'Page.createIsolatedWorld'
    discovering = {lost!r} == 'frame' or req.get('params', {{}}).get('expression') == 'globalThis.__browserUseUnmarkSession'
    if lost_error is None and discovering and req.get('method') == method:
        # Invalid ids reproduce Chrome's navigation context/frame errors on this tab's first discovery.
        params = dict(req['params'])
        params.update({{'contextId': 987654}} if {lost!r} == 'context' else {{'frameId': 'gone-before-discovery'}})
        try:
            return original_send({{**req, 'params': params}}, *args, **kwargs)
        except RuntimeError as error:
            lost_error = str(error)
            raise
    return original_send(req, *args, **kwargs)
_helpers._send = lose_one_context
try:
    switch_tab(tab)
finally:
    _helpers._send = original_send
assert lost_error and ('Cannot find context' in lost_error or 'No frame' in lost_error), lost_error
# No further tab selection: the registration must survive a navigation after the failed discovery.
goto_url('data:text/html,<title>Recovered</title><body>after</body>'); wait_for_load()
print(cdp('Runtime.evaluate', expression={mark_title_js!r}, awaitPromise=True, returnByValue=True)['result']['value'])""",
			30,
		)
		assert r['error'] is None and r['output'].strip() == 'Recovered', r
	finally:
		await repl.close()
		_shutdown_daemon(name)


@pytest.mark.parametrize('phase', ['discovery', 'registration'])
async def test_title_registration_keeps_its_session_when_another_client_switches_tabs(chrome, tmp_path, phase):
	name = f'butesttitlerace{os.getpid()}{phase}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws'], 'BH_TAB_MARKER': '1'})
	repl = Repl(tmp_path, env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
	mark_title_js = """(async () => {
  document.title = '\\u{1F434} Selected';
  await Promise.resolve();
  return document.title;
})()"""
	try:
		r = await repl.call(
			'exec',
			f"""import json
import browser_harness.helpers as _helpers
from browser_use.browser.browser import _daemon_request as outside_request
selected = cdp('Target.createTarget', url='about:blank')['targetId']
other = cdp('Target.createTarget', url='about:blank')['targetId']
other_session = cdp('Target.attachToTarget', targetId=other, flatten=True)['sessionId']
original_send = _helpers._send
switched = False
def switch_before_registration(req, *args, **kwargs):
    global switched
    method = 'Page.getFrameTree' if {phase!r} == 'discovery' else 'Page.addScriptToEvaluateOnNewDocument'
    discovering = {phase!r} == 'discovery' or req.get('params', {{}}).get('worldName') == 'browser-use-unmark'
    if not switched and req.get('method') == method and discovering:
        switched = True
        # A separate client changes the daemon's implicit session during discovery or just before registration.
        outside_request({name!r}, {{'meta': 'set_session', 'session_id': other_session, 'target_id': other}})
    return original_send(req, *args, **kwargs)
_helpers._send = switch_before_registration
try:
    selected_session = switch_tab(selected)
finally:
    _helpers._send = original_send
assert switched
# Restore the selection without running unmark() again: it must have registered on the selected session already.
outside_request({name!r}, {{'meta': 'set_session', 'session_id': selected_session, 'target_id': selected}})
goto_url('data:text/html,<title>Selected</title>'); wait_for_load()
title = cdp('Runtime.evaluate', expression={mark_title_js!r}, awaitPromise=True, returnByValue=True)['result']['value']
frame = cdp('Page.getFrameTree', session_id=other_session)['frameTree']['frame']['id']
world = cdp('Page.createIsolatedWorld', session_id=other_session, frameId=frame, worldName='browser-use-unmark')['executionContextId']
owner = cdp('Runtime.evaluate', session_id=other_session, contextId=world, expression='globalThis.__browserUseUnmarkSession', returnByValue=True)['result'].get('value')
print(json.dumps({{'title': title, 'other_owner': owner}}))""",
			30,
		)
		assert r['error'] is None, r
		assert json.loads(r['output']) == {'title': 'Selected', 'other_owner': None}, r
	finally:
		await repl.close()
		_shutdown_daemon(name)


async def test_startup_does_not_cache_another_tabs_session(chrome, tmp_path, monkeypatch):
	from browser_use.repl import session as repl_session

	name = f'butesttitlestartup{os.getpid()}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws'], 'BH_TAB_MARKER': '1'})
	cdp = lambda method, **params: _daemon_cdp(name, method, **params)
	selected = cdp('Target.createTarget', url='about:blank')['targetId']
	other = cdp('Target.createTarget', url='about:blank')['targetId']
	selected_session = cdp('Target.attachToTarget', targetId=selected, flatten=True)['sessionId']
	other_session = cdp('Target.attachToTarget', targetId=other, flatten=True)['sessionId']
	_daemon_request(name, {'meta': 'set_session', 'session_id': selected_session, 'target_id': selected})
	marker = tmp_path / 'startup-interleaving'
	bootstrap = f"""import runpy
from pathlib import Path
from browser_harness import helpers
from browser_use.browser.browser import _daemon_request
original_send = helpers._send
switched = False
def switch_after_snapshot(req, *args, **kwargs):
    global switched
    result = original_send(req, *args, **kwargs)
    if not switched and req.get('meta') in ('current_tab', 'connection_status'):
        switched = True
        _daemon_request({name!r}, {{'meta': 'set_session', 'session_id': {other_session!r}, 'target_id': {other!r}}})
        Path({str(marker)!r}).write_text(req['meta'])
    return result
helpers._send = switch_after_snapshot
runpy.run_module('browser_use.repl.worker', run_name='__main__')
"""
	original_popen = repl_session.subprocess.Popen

	def launch(command, *args, **kwargs):
		if command[1:] == ['-P', '-m', 'browser_use.repl.worker']:
			command = [command[0], '-P', '-c', bootstrap]
		return original_popen(command, *args, **kwargs)

	# Run the normal worker entrypoint with an interleaving hook installed before _install() reads its first snapshot.
	monkeypatch.setattr(repl_session.subprocess, 'Popen', launch)
	repl = Repl(tmp_path, env={'BU_NAME': name, 'BU_SHARED_DAEMON': '1'})
	mark_title_js = """(async () => {
  document.title = '\\u{1F434} Selected';
  await Promise.resolve();
  return document.title;
})()"""
	try:
		r = await repl.call(
			'exec',
			f"""switch_tab({selected!r})
goto_url('data:text/html,<title>Selected</title>'); wait_for_load()
print(cdp('Runtime.evaluate', expression={mark_title_js!r}, awaitPromise=True, returnByValue=True)['result']['value'])""",
			30,
		)
		assert marker.read_text() in {'current_tab', 'connection_status'}
		assert r['error'] is None and r['output'].strip() == 'Selected', r
	finally:
		await repl.close()
		_shutdown_daemon(name)
