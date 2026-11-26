"""Trusted mouse travel before clicks (browser_use/mouse.py): Akamai validates _abck only after real mouseMoved travel."""

import json
import re
import time

from browser_use.mouse import Mouse
from browser_use.repl import Repl
from tests.ci.test_ultrafast import IDOF, PAGES, cell, repl, site  # noqa: F401  (fixtures)


class FakeCdp:
	def __init__(self, state='visible', delay=0.0):
		self.state, self.delay, self.calls = state, delay, []

	def __call__(self, method, session_id=None, **params):
		self.calls.append((method, params))
		if method == 'Runtime.evaluate':
			return {'result': {'value': [self.state, 1280, 800]}}
		time.sleep(self.delay)
		return {}

	def mouse(self):
		return [(p['type'], p['x'], p['y']) for m, p in self.calls if m == 'Input.dispatchMouseEvent']


def test_click_travels_a_curved_path_then_presses_on_the_target():
	cdp = FakeCdp()
	Mouse(cdp).click(300, 200)
	events = cdp.mouse()
	moves = [(x, y) for t, x, y in events if t == 'mouseMoved']
	assert 10 <= len(moves) <= 14 and moves[-1] == (300, 200)
	assert [t for t, *_ in events[-2:]] == ['mousePressed', 'mouseReleased'] and events[-1][1:] == (300, 200)
	(x0, y0), (x1, y1) = moves[0], moves[-1]  # curved: some point is off the straight line from start to target
	assert max(abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) for x, y in moves) > 1


def test_next_path_starts_where_the_pointer_is():
	cdp = FakeCdp()
	m = Mouse(cdp)
	m.click(300, 200)
	cdp.calls.clear()
	m.move_to(600, 400)
	moves = [(x, y) for t, x, y in cdp.mouse()]
	assert moves[-1] == (600, 400) and abs(moves[0][0] - 300) < 150 and abs(moves[0][1] - 200) < 150


def test_hidden_tab_gets_no_path_but_still_a_trusted_click():
	"""Chrome acks each mouseMoved to a background tab only after ~5 s: a path there would take a minute."""
	cdp = FakeCdp(state='hidden')
	Mouse(cdp).click(10, 20)
	assert [t for t, *_ in cdp.mouse()] == ['mousePressed', 'mouseReleased']


def test_slow_cdp_link_does_not_pace_the_path():
	"""A cloud browser ~80 ms away: moves waited on one by one cost ~0.7 s per click, so they go out without waiting."""
	cdp = FakeCdp(delay=0.3)
	started = time.monotonic()
	Mouse(cdp).move_to(50, 60)
	moves = cdp.mouse()
	assert len(moves) >= 10 and ('mouseMoved', 50, 60) in moves
	# waiting on each reply would take >= len(moves) * 0.3 s (>= 3 s); pipelined is the path time plus one reply.
	# Half the serial floor leaves room for slow CI sleeps (macOS runners overshoot 10 ms sleeps a lot).
	assert time.monotonic() - started < len(moves) * 0.3 / 2


TRACK = """<title>Track</title><input aria-label="Email"><button>Sign in</button>
<script>window.seen = [];
for (const t of ['mousemove', 'mousedown', 'mouseup', 'click', 'focus'])
  document.addEventListener(t, e => seen.push([t, e.isTrusted, e.clientX, e.clientY]), true);</script>"""
PAGES['/track'] = TRACK


def _seen(out: str) -> list:
	m = re.search(r'SEEN(.*)', out)
	assert m, out
	return json.loads(m.group(1))


async def _open_visible(r: Repl, url: str):
	"""Tests open background tabs (new_tab), where no path is sent: show this one, as a cloud browser's tab is."""
	out, err = await cell(
		r,
		f"new_tab('{url}/track'); cdp('Target.activateTarget', targetId=current_tab()['targetId']); "
		"wait_for_load(); print(js('document.visibilityState'))",
	)
	assert err is None and out.strip().endswith('visible'), (out, err)


async def test_bu_click_and_type_move_the_mouse_and_focus_by_trusted_click(repl, site):  # noqa: F811
	await _open_visible(repl, site)
	out, err = await cell(repl, IDOF + "bu.type(idof('Email'), 'a@b.c'); bu.click(idof('Sign in'))")
	assert err is None, (out, err)
	out, err = await cell(repl, "print('SEEN' + json.dumps(js('seen')))")
	seen = _seen(out)
	assert all(trusted for _, trusted, *_ in seen), seen
	kinds = [t for t, *_ in seen]
	assert kinds.index('focus') > kinds.index('mousedown')  # the field got focus from a click, not DOM.focus
	# a path before each of the two clicks (Chrome coalesces moves that arrive within one frame)
	downs = [i for i, k in enumerate(kinds) if k == 'mousedown']
	assert len(downs) == 2 and kinds[: downs[0]].count('mousemove') >= 3, kinds
	assert kinds[downs[0] : downs[1]].count('mousemove') >= 3, kinds


async def test_click_at_xy_moves_the_mouse_first(daemon, tmp_path, site):  # noqa: F811
	r = Repl(tmp_path, daemon)
	try:
		await _open_visible(r, site)
		out, err = await cell(
			r,
			"q = cdp('DOM.getBoxModel', backendNodeId=cdp('DOM.querySelector', nodeId=cdp('DOM.getDocument')['root']"
			"['nodeId'], selector='button')['nodeId'])['model']['content']; click_at_xy(sum(q[0::2])/4, sum(q[1::2])/4); "
			"print('SEEN' + json.dumps(js('seen')))",
		)
		assert err is None, (out, err)
		seen = [e for e in _seen(out) if e[1]]
		kinds = [t for t, *_ in seen]
		assert kinds.count('mousemove') >= 3 and kinds.index('mousedown') > kinds.index('mousemove')
		down = kinds.index('mousedown')
		assert seen[down - 1][0] == 'mousemove' and seen[down - 1][2:] == seen[down][2:]  # the path ends where it presses
	finally:
		await r.close()


async def test_type_secret_with_an_id_focuses_the_field_by_a_trusted_click(daemon, tmp_path, site):  # noqa: F811
	r = Repl(tmp_path, daemon, secrets={'pw': 'hunter2-Zq9'})
	try:
		await _open_visible(r, site)
		out, err = await cell(
			r,
			"n = cdp('DOM.querySelector', nodeId=cdp('DOM.getDocument')['root']['nodeId'], selector='input')['nodeId']; "
			"type_secret('pw', cdp('DOM.describeNode', nodeId=n)['node']['backendNodeId']); "
			"print('SEEN' + json.dumps(js('seen')), js('document.querySelector(\"input\").value.length'))",
		)
		assert err is None, (out, err)
		kinds = [t for t, trusted, *_ in _seen(out.rsplit(' ', 1)[0]) if trusted]
		assert 'mousemove' in kinds and kinds.index('mousedown') < kinds.index('focus'), kinds
		assert out.strip().endswith(' 11')
	finally:
		await r.close()
