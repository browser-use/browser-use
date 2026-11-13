"""Frame helpers exercise the real worker, IPC and isolated Chrome."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from browser_use.repl import Repl


@pytest.fixture
def frame_site():
	class Handler(BaseHTTPRequestHandler):
		def log_message(self, *_):
			pass

		def do_GET(self):
			if self.path.startswith('/inner'):
				body = '<title>inner</title><script>window.application = {value: 42}</script><input id="edit">'
			elif self.path.startswith('/outer'):
				body = '<title>outer</title><iframe src="/inner"></iframe>'
			else:
				host = f'http://localhost:{self.server.server_port}' if self.path.startswith('/cross') else ''
				body = f'<title>top</title><iframe src="{host}/outer"></iframe>'
			self.send_response(200)
			self.send_header('Content-Type', 'text/html')
			self.end_headers()
			self.wfile.write(body.encode())

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	yield f'http://127.0.0.1:{server.server_port}'
	server.shutdown()
	server.server_close()
	thread.join()


async def cell(repl, code):
	result = await repl.call('exec', code, 30)
	assert result['error'] is None, result
	return result


@pytest.mark.parametrize('path', ['/same', '/cross'])
async def test_nested_frame_main_world_and_no_global_switch(daemon, tmp_path, frame_site, path):
	r = Repl(tmp_path, daemon)
	try:
		await cell(r, f'new_tab({frame_site + path!r}); wait_for_load()')
		out = await cell(
			r,
			"frames = frame_list(); print(frames)\nf = next(f for f in frames if f['url'].endswith('/inner'))\n"
			"print(frame_eval(f, 'window.application.value'), frame_eval(f, 'document.title'))\n"
			"print(frame_eval(f, 'Promise.resolve(43)'))\nprint(js('document.title'))",
		)
		assert '42 inner' in out['output'] and '43' in out['output'] and out['output'].endswith('top\n')
		assert out['stats']['helpers']['frame_eval'] == 3
		# The application's global was defined only in its main world, not the isolated inspection world.
		await cell(r, "assert len(frames) == 3; assert frames[0]['frame_id'] != f['frame_id']")
		await cell(
			r,
			"targets = {t['targetId'] for t in cdp('Target.getTargets')['targetInfos'] if t['type'] == 'iframe'}\n"
			+ (
				"assert f['target_id'] != f['tab_id'] and f['target_id'] in targets"
				if path == '/cross'
				else "assert f['target_id'] == f['tab_id']"
			),
		)
	finally:
		await r.close()


@pytest.mark.parametrize(
	'mutation', ["document.querySelector('iframe').remove()", "document.querySelector('iframe').src = '/inner?new'"]
)
async def test_removed_or_navigated_ref_never_falls_back(daemon, tmp_path, frame_site, mutation):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({frame_site + "/cross"!r}); wait_for_load()\n'
			"f = next(f for f in frame_list() if f['url'].endswith('/outer'))",
		)
		await cell(r, f'js({mutation!r})\nimport time\ntime.sleep(.3)')
		out = await r.call('exec', "frame_eval(f, 'window.unexpected = true')", 30)
		assert out['error'] and 'removed or navigated' in out['error']
		await cell(r, "assert js('!!window.unexpected') is False")
	finally:
		await r.close()


async def test_tab_ownership_and_duplicate_urls(daemon, tmp_path, frame_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r, f"new_tab({frame_site + '/same'!r}); wait_for_load()\nfirst = current_tab()['targetId']; f = frame_list()[1]"
		)
		await cell(r, f'new_tab({frame_site + "/same"!r}); wait_for_load()')
		out = await r.call('exec', "frame_eval(f, 'window.unexpected = true')", 30)
		assert 'another tab' in out['error']
		await cell(
			r,
			"assert js('!!window.unexpected') is False\nswitch_tab(first)\n"
			'js("document.body.appendChild(document.querySelector(\'iframe\').cloneNode())")\n'
			'import time; time.sleep(.2)\n'
			"same = [f for f in frame_list() if f['url'].endswith('/outer')]\n"
			"assert len(same) == 2 and same[0]['frame_id'] != same[1]['frame_id']\n"
			"frame_eval(same[0], 'window.selected = true')\nassert frame_eval(same[1], '!!window.selected') is False",
		)
	finally:
		await r.close()


async def test_navigation_during_document_resolution_rejects_old_ref(daemon, tmp_path, frame_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({frame_site + "/same"!r}); wait_for_load()\n'
			"f = next(f for f in frame_list() if f['url'].endswith('/outer'))\n"
			'import browser_harness.helpers as h, time\nraw = h.cdp\nmoved = False\n'
			'def navigate_during_resolution(method, *a, **kw):\n'
			'    global moved\n'
			"    if method == 'Page.createIsolatedWorld' and not moved:\n"
			'        moved = True\n'
			f"        raw('Page.navigate', frameId=f['frame_id'], url={frame_site + '/outer?new'!r})\n"
			'        end = time.monotonic() + 3\n'
			'        while time.monotonic() < end:\n'
			"            if any(x['id'] == f['frame_id'] and x['loaderId'] != f['loader_id'] for x in [raw('Page.getFrameTree')['frameTree']['childFrames'][0]['frame']]): break\n"
			'            time.sleep(.01)\n'
			"        assert raw('Page.getFrameTree')['frameTree']['childFrames'][0]['frame']['loaderId'] != f['loader_id']\n"
			'    return raw(method, *a, **kw)\n'
			'h.cdp = navigate_during_resolution',
		)
		out = await r.call('exec', "frame_eval(f, 'window.unexpected = true')", 30)
		assert out['error'] and 'changed' in out['error'], out
		await cell(
			r,
			'h.cdp = raw\nassert moved\n'
			"fresh = next(x for x in frame_list() if '/outer?new' in x['url'])\n"
			"assert frame_eval(fresh, '!!window.unexpected') is False\nassert js('!!window.unexpected') is False",
		)
	finally:
		await r.close()


async def test_error_once_cleanup_and_no_event_consumption(daemon, tmp_path, frame_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({frame_site + "/cross"!r}); wait_for_load()\n'
			'import browser_harness.helpers as h\nraw_cdp = h.cdp; calls = []\n'
			'def tracked(method, *a, **kw):\n    calls.append(method)\n    return raw_cdp(method, *a, **kw)\n'
			"h.cdp = tracked\nh.drain_events = lambda: (_ for _ in ()).throw(AssertionError('drained'))\n"
			"f = next(f for f in frame_list() if f['url'].endswith('/inner'))",
		)
		out = await r.call(
			'exec', 'frame_eval(f, \'(()=>{window.count=(window.count||0)+1;throw new Error("expected")})()\')', 30
		)
		assert 'expected' in out['error']
		await cell(
			r,
			"assert frame_eval(f, 'window.count') == 1\n"
			"assert calls.count('Target.attachToTarget') == calls.count('Target.detachFromTarget')\n"
			"assert calls.count('Runtime.releaseObjectGroup') == 2",
		)
	finally:
		await r.close()


async def test_promise_timeout_is_not_retried(daemon, tmp_path, frame_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(r, f'new_tab({frame_site + "/same"!r}); wait_for_load()\nf=frame_list()[0]')
		out = await r.call(
			'exec', "frame_eval(f, '(()=>{window.count=(window.count||0)+1;return new Promise(()=>{})})()', timeout_s=.5)", 30
		)
		assert out['error']
		await cell(r, "assert js('window.count') == 1")
	finally:
		await r.close()


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), True])
def test_invalid_timeout(timeout):
	from browser_use.repl.frames import frame_list

	with pytest.raises(ValueError, match='finite positive'):
		frame_list(timeout_s=timeout)
