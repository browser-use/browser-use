"""Ultrafast mode (port of Browser Use Pi src/ax.ts) against a real headless Chrome; no provider calls."""

import hashlib
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
from browser_use.agent.loop import build_agent
from browser_use.agent.prompt import SYSTEM_PROMPT
from browser_use.ax import AX_PROMPT
from browser_use.llm import GATEWAY_URL
from browser_use.repl import Repl

PAGES = {
	'/form': """<title>Demo</title><h1>Book a trip</h1><p>Pick a city and a date.</p>
<label for=city>City</label><input id=city value="Bern">
<label><input type=checkbox checked> Flexible</label>
<select aria-label="Country"><option>Austria<option>Canada<option>Chile<option>Denmark<option>Estonia<option>France<option>Ghana</select>
<input type=date aria-label="Day">
<button aria-expanded=false onclick="this.setAttribute('aria-expanded','true')">Details</button>
<button disabled>Unavailable</button>
<div style="opacity:0">Secret success</div>
<a href="/next">Next page</a>""",
	'/next': '<title>Next</title><p>Second page</p>',
	'/locked': """<title>Locked</title><select id=a disabled><option>A<option>B</select>
<fieldset disabled><input id=b type=date></fieldset><div inert><select id=c><option>A<option>B</select></div>
<select id=d style="display:none"><option>A<option>B</select><span aria-disabled=true><input id=e type=time></span>""",
	'/act': """<title>Act</title>
<form action="/next"><input aria-label="Query" name=q></form>
<button onclick="document.getElementById('out').textContent = 'Clicked'">Go</button>
<button>Noop</button>
<button onclick="fetch('/slow').then(r => r.text()).then(t => document.getElementById('out').textContent = t)">Fetch</button>
<button onclick="alert('Hello there'); document.getElementById('out').textContent = confirm('Sure?') ? 'confirmed' : 'denied'">Alert</button>
<button onclick="setTimeout(() => document.getElementById('more').innerHTML = '<button>Fresh</button>', 0)">Reveal</button>
<div id=more></div>
<div style="position:relative"><button>Under</button>
  <div role=dialog aria-label="Cookie banner" style="position:absolute;inset:0;background:white">We use cookies</div></div>
<button style="display:none">Gone</button>
<p id=out></p>""",
	'/frames': """<title>Frames</title><div id=host></div>
<script>document.getElementById('host').attachShadow({mode: 'open'}).innerHTML = '<button>Shadow button</button>'</script>
<iframe src="/inner" style="border:0;padding:10px"></iframe>
<label class=up>Upload CV<input type=file name=cv style="display:none"></label>""",
	# Brooklinen: the search field says aria-disabled but takes focus and typing.
	'/aria': """<title>Aria</title><form action="/next"><input aria-label="Search" name=q aria-disabled=true></form>""",
	'/hidden': '<title>Hidden</title><main aria-hidden=true><button>Behind popup</button></main>',
	'/inner': """<title>Inner</title><button onclick="this.textContent = 'Inner done'">Inner button</button>""",
	# A lone surrogate, as left by text cut in the middle of an emoji.
	'/emoji': r"""<title>Emoji</title><input aria-label="Note">
<button onclick="document.getElementById('out').textContent = 'Tweet text \ud83d'; document.querySelector('input').value = 'x\ud83d'">Cut</button>
<p id=out></p>""",
	# Non-breaking spaces (U+00A0, U+202F), as eBay and Airbnb print prices and dates.
	'/nbsp': '<title>Nbsp</title><p>US&nbsp;$12.99 for 5&#x202F;nights</p><button>Pay&nbsp;now</button>'
	'<table><tr><td>A</td><td>&nbsp;</td><td>B</td></tr></table><a href="#">&nbsp;</a>',
	# jqueryui.com/datepicker: the calendar lives in a same-origin iframe; each click there changes only the iframe.
	'/picker': '<title>Picker</title><h1>Demo</h1><iframe src="/month" style="border:0;height:200px"></iframe>',
	'/month': """<title>Month</title><p id=m>November</p>
<button onclick="document.getElementById('m').textContent = 'December'">Next month</button><button>Idle</button>""",
	# demoqa.com: a fixed footer covers the bottom of the viewport, and a field sits right above the fold under it.
	'/footer': """<title>Footer</title><div style="height:calc(100vh - 60px)"></div>
<button onclick="this.textContent = 'Saved'">Save</button><div style="height:2000px"></div>
<footer style="position:fixed;bottom:0;left:0;right:0;height:120px;background:#eee">Site footer</footer>""",
	# the-internet.herokuapp.com/basic_auth: a 401 Basic Auth challenge fails the navigation to a blank error page.
	'/dead': '<title>Dead</title><a href="/auth">Staging site</a>',
	'/long': '<title>Long</title>' + ''.join(f'<button>Item number {i}</button>' for i in range(60)),
}


class Handler(BaseHTTPRequestHandler):
	def do_GET(self):
		path = self.path.split('?')[0]
		if path == '/auth':
			self.send_response(401)
			self.send_header('WWW-Authenticate', 'Basic realm="staging"')
			self.send_header('Content-Length', '0')
			self.end_headers()
			return
		if path == '/slow':
			time.sleep(0.5)  # longer than the 80 ms quiet window: settle must wait on the request
			body = b'Loaded'
		else:
			body = PAGES.get(path, '').encode()
		self.send_response(200 if path == '/slow' or path in PAGES else 404)
		self.send_header('Content-Type', 'text/html')
		self.send_header('Content-Length', str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *args):
		pass


@pytest.fixture(scope='module')
def site():
	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'http://127.0.0.1:{server.server_address[1]}'
	server.shutdown()
	server.server_close()


@pytest.fixture
async def repl(daemon, tmp_path):
	r = Repl(tmp_path, daemon, mode='ultrafast')
	yield r
	await r.close()


async def cell(repl, code, timeout=60):
	r = await repl.call('exec', code, timeout)
	return r['output'], r['error']


IDOF = """
import contextlib, io, re
def idof(name):
    with contextlib.redirect_stdout(io.StringIO()):  # look up an id without printing the state
        return int(re.search(r'\\[(\\d+)\\] \\w+ "' + re.escape(name), bu.state()).group(1))
"""


def ids(text):
	return re.sub(r'\[\d+\]', '[N]', text)


# --- mode option and the unchanged default path ---


def test_mode_validation(tmp_path):
	for bad in ('fast', 'Ultrafast', ''):
		with pytest.raises(ValueError, match="mode must be 'default' or 'ultrafast'."):
			Agent('t', 'test', mode=bad, workspace=tmp_path)
		with pytest.raises(ValueError, match="mode must be 'default' or 'ultrafast'."):
			build_agent('test', mode=bad)
		with pytest.raises(ValueError, match="mode must be 'default' or 'ultrafast'."):
			Repl(tmp_path, mode=bad)
	assert Agent('t', 'test', workspace=tmp_path).mode == 'default'
	assert Agent('t', 'test', workspace=tmp_path, mode=None).mode == 'default'  # Pi: undefined means 'default'
	assert Repl(tmp_path, mode='ultrafast').mode == 'ultrafast'


def static_instructions(agent):
	return [i.instruction for i in agent._instructions if isinstance(i.instruction, str)]


def test_default_prompt_unchanged():
	"""Default mode is the evaluated path: its system prompt must stay byte-identical (sha256 from 0.2.0, plus the
	finish success line that made success required, minus the finish-whole-job and verify-answer paragraphs bu-pi lacks,
	and the downloads line no longer telling the model to call Browser.setDownloadBehavior: C12; http_get says it runs
	from this machine, not the browser, and returns bytes for binary: C31; native <select> is set in page code, never
	clicked: C34; downloads are checked with downloads(), not Browser.downloadProgress events, which a cell drained
	before they arrived, so the model clicked again; uploads take the task's existing file, which the agent never creates
	or overwrites, without the hand-written DataTransfer fallback upload_file now does itself: t8_files; report_issue()
	tells the Browser Use team when browser-use gets in the agent's way, a missing helper included: library_feedback)."""
	default = static_instructions(build_agent())
	assert default == [SYSTEM_PROMPT] == static_instructions(build_agent(mode='default'))
	assert hashlib.sha256(default[0].encode()).hexdigest() == '01cd1da6278fdb263bcca92a24adf61a949efd26445a54a8cfab373a1c506023'
	assert static_instructions(build_agent(instructions='X')) == [f'{SYSTEM_PROMPT}\nX']
	assert static_instructions(build_agent(mode='ultrafast')) == [(SYSTEM_PROMPT + AX_PROMPT).rstrip()]
	assert static_instructions(build_agent(mode='ultrafast', instructions='X')) == [f'{SYSTEM_PROMPT}{AX_PROMPT}\nX']
	assert build_agent(mode='ultrafast').model_settings == build_agent().model_settings


async def test_default_worker_has_no_bu(daemon, tmp_path, monkeypatch):
	monkeypatch.setenv('BU_MODE', 'ultrafast')  # a leftover shell variable must not switch the mode
	r = Repl(tmp_path, daemon)
	try:
		out, err = await cell(r, "print('bu' in globals(), drain_events.__module__, os.environ.get('BU_MODE'))")
		assert err is None and out.strip() == 'False browser_use.repl.captcha None'  # EventPump, not bu
	finally:
		await r.close()


# --- bu.state() ---


async def test_state_format(repl, site):
	out, err = await cell(repl, f"new_tab('{site}/form'); bu.state()")
	assert err is None, err
	assert (
		ids(out)
		== f"""[state] Demo | {site}/form
## Book a trip
Pick a city and a date.
[N] textbox "City" = "Bern"
[N] checkbox "Flexible" checked
[N] select "Country" = "Austria" collapsed  options: Austria | Canada | Chile | Denmark | Estonia | … 2 more
[N] Date "Day"
[N] button "Details" collapsed
[N] button "Unavailable" disabled
[N] link "Next page"
[/state]
"""
	)  # the opacity:0 "Secret success" is in the AX tree but not shown, so not printed
	# Returned text equals the print; the REPL does not echo it a second time.
	out, err = await cell(repl, "s = bu.state(); print(type(s).__name__, s.startswith('[state] Demo'), s.endswith('[/state]'))")
	assert out.count('[state]') == 1 and out.strip().endswith('Printed True True')
	# Pi: console.log(await bu.state()) prints an empty line, not the state again.
	out, err = await cell(repl, "print(bu.state()); print('x', bu.state(), 'y')")
	assert err is None and out.count('[state]') == 2 and '[/state]\n\n[state]' in out and out.endswith('[/state]\nx  y\n'), out


async def test_state_marks_new_ids_and_truncates(repl, site):
	out, err = await cell(repl, f"new_tab('{site}/act'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Reveal'))")
	assert err is None, err
	new = [line for line in out.splitlines() if line.startswith('*')]
	assert len(new) == 1 and re.fullmatch(r'\*\[\d+\] button "Fresh"', new[0]), out
	out, err = await cell(repl, f"goto_url('{site}/long'); bu.state(max=300)")
	assert err is None, err
	lines = out.strip().splitlines()
	assert lines[0] == f'[state] Long | {site}/long' and lines[-1] == '[/state]'
	cut = [line for line in lines if 'lines cut here' in line]
	assert cut and re.fullmatch(r'\.\.\. \d+ lines cut here \(bu\.state\(max=30000\) or js\(\.\.\.\)\)', cut[0])
	assert lines[-2].endswith('button "Item number 59"')  # the last fifth is kept
	assert 260 <= len('\n'.join(lines[1:-1])) <= 400


async def test_state_shadow_dom_iframe_and_hidden_file_input(repl, site):
	out, err = await cell(repl, f"new_tab('{site}/frames'); bu.state()" + IDOF)
	assert err is None, err
	body = ids(out)
	assert body.startswith(f'[state] Frames | {site}/frames\n[N] file "cv" (hidden)\n'), out
	assert '[N] button "Shadow button"' in body
	assert f'--- frame {site}/inner ---\n[N] button "Inner button"' in body
	# Ids inside a same-origin iframe click at top-level coordinates (frame offset + padding added).
	out, err = await cell(repl, "bu.click(idof('Inner button'))")
	assert err is None, err
	assert re.search(r'\[ok\] click \[\d+\] button "Inner button" -> page changed', out), out
	assert 'button "Inner done"' in out


async def test_a_change_inside_a_same_origin_iframe_is_reported(repl, site):
	"""Customer task (jqueryui.com datepicker, bu-fast): Pi's probe watched only the top document, so every click in
	the demo iframe printed "no change" while the calendar moved a month; the agent distrusted bu and spent 10 steps on
	frame trees and screenshots. A click there that changes nothing still says so."""
	await cell(repl, f"new_tab('{site}/picker'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Next month'))")
	assert err is None and re.match(r'\[ok\] click \[\d+\] button "Next month" -> page changed\n', out), out
	assert 'December' in out.split('[state]')[1]
	out, err = await cell(repl, "bu.click(idof('Idle'))")
	assert err is None and re.match(r'\[ok\] click \[\d+\] button "Idle" -> no change\n', out), out


async def test_a_failed_navigation_names_the_net_error(repl, site):
	"""Customer task (the-internet.herokuapp.com, 40 examples, bu-fast on a cloud browser): the Basic Auth link printed
	"navigated to chrome-error://chromewebdata/" and a state that blamed a blank page or a popup in a cross-origin
	iframe. The page had failed to load (net::ERR_INVALID_AUTH_CREDENTIALS); the agent could not tell why."""
	await cell(repl, f"new_tab('{site}/dead'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Staging site'))")
	assert err is None, err
	assert re.match(
		r'\[ok\] click \[\d+\] link "Staging site" -> navigated to chrome-error://chromewebdata/ '
		r'\(net::ERR_INVALID_AUTH_CREDENTIALS\)\n',
		out,
	), out
	assert '(the page did not load: net::ERR_INVALID_AUTH_CREDENTIALS' in out.split('[state]')[1], out
	assert 'popup' not in out.split('[state]')[1], out
	out, err = await cell(repl, f"goto_url('{site}/next'); print(bu.state())")  # a later page that loads: no stale error
	assert err is None and 'Second page' in out and 'net::' not in out, out


async def test_a_target_under_a_fixed_footer_is_scrolled_clear_and_clicked(repl, site):
	"""Customer task (demoqa.com practice form, bu-fast): a field just above the fold sat under the site's fixed
	footer. It counted as visible, so scrollIntoViewIfNeeded did not move it, and bu.type/bu.click failed "covered by
	contentinfo" 3 times; the agent took 6 steps to click by coordinates."""
	await cell(repl, f"new_tab('{site}/footer'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Save'))")
	assert err is None and re.match(r'\[ok\] click \[\d+\] button "Save" -> page changed\n', out), (out, err)
	assert 'button "Saved"' in out


# --- actions ---


async def test_click_and_type_by_id(repl, site):
	await cell(repl, f"new_tab('{site}/act'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Go'))")
	assert err is None, err
	first, *rest = out.splitlines()
	assert re.fullmatch(r'\[ok\] click \[\d+\] button "Go" -> page changed', first), out
	assert rest[0] == f'[state] Act | {site}/act' and 'Clicked' in rest and rest[-1] == '[/state]'  # printed automatically

	out, err = await cell(repl, "bu.type(idof('Query'), 'Zurich')")
	assert err is None and re.match(r'\[ok\] type \[\d+\] textbox "Query" = "Zurich" -> page changed\n', out), out
	assert re.search(r'textbox "Query" = "Zurich" focused', out)
	out, err = await cell(repl, "bu.type(idof('Query'), 'Bern', enter=True)")
	assert err is None and re.match(
		rf'\[ok\] type \[\d+\] textbox "Query" = "Bern" \+Enter -> navigated to {site}/next\?q=Bern\n', out
	), out
	assert f'[state] Next | {site}/next?q=Bern' in out and 'Second page' in out


async def test_type_select_date_and_clear(repl, site):
	await cell(repl, f"new_tab('{site}/form'); s = bu.state()" + IDOF)
	out, err = await cell(
		repl,
		"print(bu.type(idof('Country'), 'can')); print(bu.type(idof('Day'), '2026-10-14')); print(bu.type(idof('City'), ''))",
	)
	assert err is None, err
	assert re.search(r'^\[ok\] type \[\d+\] select "Country" = "Canada" -> page changed$', out, re.M), out
	assert re.search(r'^\[ok\] type \[\d+\] Date "Day" = "2026-10-14" -> page changed$', out, re.M), out
	assert re.search(r'^\[ok\] type \[\d+\] textbox "City" = "" -> page changed$', out, re.M), out
	assert 'select "Country" = "Canada"' in out and 'Date "Day" = "2026-10-14"' in out
	assert re.search(r'textbox "City" focused', out)
	out, err = await cell(repl, "bu.type(idof('Country'), 'C')")
	assert 'several options start with "C". Options: Canada | Chile' in err
	out, err = await cell(repl, "bu.type(idof('Day'), 'Oct 14')")
	assert 'Invalid native date/time value; use its ISO format' in err
	out, err = await cell(repl, "bu.type(idof('City'), 5)")
	assert 'TypeError: type needs a string.' in err


async def test_type_refuses_disabled_inert_and_hidden_native_controls(repl, site):
	"""Roast r2-10: selects and date/time inputs were set directly, before the disabled/inert/hidden checks, so
	bu.type() changed disabled controls and fired their input/change events."""
	await cell(repl, f"new_tab('{site}/locked'); wait_for_load()")
	byid = (
		'def byid(i):\n'
		"    root = cdp('DOM.getDocument', depth=0)['root']['nodeId']\n"
		"    n = cdp('DOM.querySelector', nodeId=root, selector='#' + i)['nodeId']\n"
		"    return cdp('DOM.describeNode', nodeId=n)['node']['backendNodeId']\n"
	)
	await cell(repl, byid)
	for i, value, why in [('a', 'B', 'disabled'), ('b', '2026-10-14', 'disabled'), ('c', 'B', 'disabled'),
						  ('d', 'B', 'hidden')]:  # fmt: skip
		out, err = await cell(repl, f"bu.type(byid('{i}'), '{value}')")
		assert err and f'Target {why}' in err, (i, err)
	out, err = await cell(repl, "bu.type(byid('e'), '10:30')")  # aria-disabled is a claim, not enforced: like Chrome
	assert err is None, err
	out, err = await cell(repl, "print([js(f\"document.getElementById('{i}').value\") for i in 'abcde'])")
	assert out.splitlines()[0] == "['A', '', 'A', 'A', '10:30']", out


async def test_aria_disabled_field_is_typable_and_empty_state_says_why(repl, site):
	"""C35: Brooklinen's search had aria-disabled=true yet accepted typing; ultrafast printed it disabled and refused it,
	so the model gave up. An aria-hidden page (cross-origin popup) printed an empty state with no hint."""
	out, err = await cell(repl, f"new_tab('{site}/aria'); bu.state()" + IDOF)
	assert err is None and re.search(r'^\[\d+\] textbox "Search"$', out, re.M), out
	out, err = await cell(repl, "bu.type(idof('Search'), 'pillowcase', enter=True)")
	assert err is None and f'navigated to {site}/next?q=pillowcase' in out, (out, err)
	out, err = await cell(repl, f"goto_url('{site}/hidden'); bu.state()")
	assert err is None and out.splitlines()[1].startswith('(nothing in the accessibility tree:'), out


async def test_no_change_and_failures(repl, site):
	await cell(repl, f"new_tab('{site}/act'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Under'))")
	assert re.search(
		r'RuntimeError: click \[\d+\] button "Under" failed: Target covered by \[\d+\] dialog '
		r'"Cookie banner"; nothing was clicked',
		err,
	), err
	assert 'ax.py' not in err and 'worker.py' not in err  # only the cell's own frames
	assert '[state] Act' in out  # a failed action still prints the state after its cell
	out, err = await cell(
		repl,
		"root = cdp('DOM.getDocument', depth=0)['root']['nodeId']\n"
		"n = cdp('DOM.querySelector', nodeId=root, selector='button[style*=none]')['nodeId']\n"
		"bu.click(cdp('DOM.describeNode', nodeId=n)['node']['backendNodeId'])",
	)
	assert re.search(r'click \[\d+\] failed: Error: Target hidden', err), err
	out, err = await cell(repl, 'bu.click(999999)')  # a stale id: CDP's error, worded like Pi's cdp.ts
	assert 'RuntimeError: click [999999] failed: CDP -32000: No node with given id found' in err, err
	out, err = await cell(repl, "bu.click(idof('Noop'))")  # focus moves, the DOM does not change
	assert err is None and re.match(r'\[ok\] click \[\d+\] button "Noop" -> no change\n', out), out


async def test_lone_surrogate_prints_like_pi(repl, site):
	# Pi: console.log writes U+FFFD for a lone surrogate, JSON.stringify escapes it in values.
	await cell(repl, f"new_tab('{site}/emoji'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Cut'))")
	assert err is None, err
	assert 'Tweet text \ufffd' in out and 'textbox "Note" = "x\\ud83d"' in out, out
	out, err = await cell(repl, "s = bu.state(); print('\\ud83d' in s)")
	assert err is None and out.endswith('[/state]\nFalse\n'), out


async def test_state_keeps_non_breaking_spaces(repl, site):
	"""eval-ax-1107 bub2-020: bu.state() turned U+00A0 and U+202F into plain spaces, so prices the model copied from it
	failed exact-string checks 2 of 3 times. It prints the text as the page has it (what a user copies). A '&nbsp;'
	spacer is still no text: no stray U+00A0 between cells, and a link named only by one has no name."""
	out, err = await cell(repl, f"new_tab('{site}/nbsp'); bu.state()")
	assert err is None, err
	assert '\nUS\u00a0$12.99 for 5\u202fnights\n' in out and 'button "Pay\u00a0now"' in out, ascii(out)
	assert '\nA B\n' in out and re.search(r'\] link\n', out), ascii(out)


async def test_settle_waits_for_requests(repl, site):
	await cell(repl, f"new_tab('{site}/act'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "t = time.time(); r = bu.click(idof('Fetch')); print(round(time.time() - t, 1))")
	assert err is None, err
	assert re.search(r'\[ok\] click \[\d+\] button "Fetch" -> page changed', out), out
	assert 'Loaded' in out.split('[state]')[1]  # no sleep: the settle waited for /slow (500 ms) and its DOM update
	assert 0.5 <= float(out.split('\n')[1]) <= 1.5


async def test_dialogs_are_accepted_and_reported(repl, site):
	await cell(repl, f"new_tab('{site}/act'); s = bu.state()" + IDOF)
	out, err = await cell(repl, "bu.click(idof('Alert'))")
	assert err is None, err
	assert re.match(
		r'\[ok\] click \[\d+\] button "Alert" -> page changed\n\[dialog alert\] "Hello there" \(accepted\)\n'
		r'\[dialog confirm\] "Sure\?" \(accepted\)\n',
		out,
	), out
	assert 'confirmed' in out.split('[state]')[1]
	# A dialog the agent's own code opens is accepted too; its text goes on the next bu print.
	out, err = await cell(repl, "js('setTimeout(() => alert(\"Later\"), 0)'); print(js('1 + 1')); time.sleep(0.3); bu.state()")
	assert err is None, err
	assert out.startswith('2\n[state] Act | ') and '\n[dialog alert] "Later" (accepted)\n' in out, out


async def test_drain_events_still_returns_events(repl, site):
	out, err = await cell(
		repl,
		f"new_tab('{site}/next'); bu.state(); drain_events(); goto_url('{site}/form'); bu.state()\n"
		"ev = drain_events(); print(any(e['method'] == 'Network.requestWillBeSent' for e in ev))\n"
		'print(wait_for_network_idle(timeout=3))',
	)
	assert err is None, err
	assert out.strip().splitlines()[-2:] == ['True', 'True']


async def test_state_printed_once_per_cell(repl, site):
	out, err = await cell(repl, f"new_tab('{site}/act'); print('hi')" + IDOF)
	assert err is None and out == 'hi\n'  # no bu action: nothing printed automatically
	out, err = await cell(repl, 'bu.state()')
	assert out.count('[state]') == 1
	out, err = await cell(repl, "bu.click(idof('Go')); s = bu.state()")
	assert err is None and out.count('[state]') == 1  # a look after the last action replaces the automatic print
	out, err = await cell(repl, "s = bu.state(); bu.click(idof('Go'))")
	assert err is None and out.count('[state]') == 2 and out.rstrip().endswith('[/state]')


# --- the public API end to end ---


async def test_bu_fast_and_bu_ultrafast_default_to_ultrafast_mode(monkeypatch, tmp_path):
	"""Google Flights on bu-ultrafast (local Chrome, 3 runs each): default mode 0/3, ultrafast 3/3 in 21 s. Any gateway
	model form gets it; mode='default' opts out; other models keep the default mode."""
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(ChatBrowserUse, 'preflight', lambda self: None)
	repls = []

	async def start(self):
		return {}

	def repl(*args, mode, **kwargs):  # the mode the worker would start in; stops the run before any model request
		repls.append(mode)
		raise RuntimeError('stop')

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr('browser_use.agent.service.Repl', repl)
	for llm, mode, expected in [
		('bu-fast', None, 'ultrafast'),
		(ChatBrowserUse('bu-ultrafast'), None, 'ultrafast'),
		(ChatBrowserUse('bu-fast').pydantic_model(), None, 'ultrafast'),
		(ChatOpenAI('bu-ultrafast', base_url=GATEWAY_URL), None, 'ultrafast'),
		('bu-fast', 'default', 'default'),
		('bu-smart', None, 'default'),
	]:
		agent = Agent('t', llm, mode=mode, browser=Browser(local=True), workspace=tmp_path)
		with pytest.raises(RuntimeError, match='stop'):
			await agent.run()
		assert (AX_PROMPT.strip() in static_instructions(agent._agent)[0], repls.pop()) == (expected == 'ultrafast', expected)


async def test_agent_ultrafast_end_to_end(chrome, site, tmp_path):
	seen = []
	turns = [
		[('python', {'code': f"new_tab('{site}/act')" + IDOF + "bu.click(idof('Go'))"})],
		[('finish', {'success': True, 'result': 'done'})],
	]

	def fn(messages, info: AgentInfo):
		seen.append(messages)
		return ModelResponse(parts=[ToolCallPart(n, a) for n, a in turns[len(seen) - 1]])

	async with Agent(
		'Click Go', FunctionModel(fn), browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, mode='ultrafast'
	) as agent:
		result = await agent.run()
	assert result.final_result() == 'done'
	first = next(m for m in seen[0] if isinstance(m, ModelRequest))
	assert AX_PROMPT.strip() in first.instructions
	ret = next(p for m in seen[1] for p in getattr(m, 'parts', []) if isinstance(p, ToolReturnPart))
	text = ret.content[0]
	assert re.search(r'\[ok\] click \[\d+\] button "Go" -> page changed\n\[state\] Act', text), text
	assert '\nClicked\n' in text
