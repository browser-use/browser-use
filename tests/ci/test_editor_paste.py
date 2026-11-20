"""Synthetic paste acknowledgement is distinct from insertion and durable storage."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_frame_helpers import cell, frame_site  # noqa: F401 — real nested-frame fixture

from browser_use import Browser
from browser_use.repl import Repl


@pytest.fixture
def editor_site():
	class Handler(BaseHTTPRequestHandler):
		def log_message(self, *_):
			pass

		def do_GET(self):
			body = b"""<textarea id="edit"></textarea><pre id="saved"></pre><script>
            window.pastes = 0;
            saved.textContent = localStorage.getItem('body') || '';
            if (!location.search.includes('ignore')) edit.addEventListener('paste', event => {
                event.preventDefault(); window.pastes++;
                window.html = event.clipboardData.getData('text/html');
                saved.textContent += event.clipboardData.getData('text/plain');
                if (location.search.includes('save')) setTimeout(() => localStorage.setItem('body', saved.textContent), 40);
            });
            </script>"""
			self.send_response(200)
			self.send_header('Content-Type', 'text/html; charset=utf-8')
			self.end_headers()
			self.wfile.write(body)

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	yield f'http://127.0.0.1:{server.server_port}'
	server.shutdown()
	server.server_close()
	thread.join()


async def test_long_unicode_paste_once_below_ipc_limit(daemon, tmp_path, editor_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(r, f'new_tab({editor_site!r}); wait_for_load()')
		out = await cell(
			r,
			r"""text = '中文😀\n\\"</script>' * 5000
html = '<p>真实正文</p>'
receipt = dispatch_paste('#edit', text, html=html)
assert receipt['status'] == 'dispatched'
assert receipt['input_verified'] is False and receipt['persistence_verified'] is False
assert js('window.pastes') == 1
assert js('document.querySelector("#saved").textContent') == text
assert js('window.html') == html
""",
		)
		assert out['stats']['helpers']['dispatch_paste'] == 1
	finally:
		await r.close()


@pytest.mark.parametrize('mode, expected', [('save', 'Real section'), ('drop', '')])
async def test_reopen_distinguishes_saved_and_unsaved_content(daemon, tmp_path, editor_site, mode, expected):
	r = Repl(tmp_path, daemon)
	try:
		url = editor_site + '?' + mode
		await cell(r, f'new_tab({url!r}); wait_for_load(); js("localStorage.clear()")')
		await cell(
			r,
			"receipt = dispatch_paste('#edit', 'Real section')\n"
			"assert receipt['status'] == 'dispatched' and not receipt['persistence_verified']\n"
			"assert js('saved.textContent') == 'Real section'\nimport time; time.sleep(.15)",
		)
		if mode == 'save':
			await cell(
				r,
				"for _ in range(80):\n    if js('localStorage.getItem(\"body\")') == 'Real section': break\n    time.sleep(.05)\nassert js('localStorage.getItem(\"body\")') == 'Real section'",
			)
		await cell(r, f'goto_url({url!r}); wait_for_load()\nassert js("saved.textContent") == {expected!r}')
	finally:
		await r.close()


async def test_editor_without_handler_does_not_claim_input(daemon, tmp_path, editor_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(r, f'new_tab({editor_site + "?ignore"!r}); wait_for_load()')
		await cell(
			r,
			"receipt=dispatch_paste('#edit', 'Will not insert')\n"
			"assert receipt['status'] == 'dispatched' and not receipt['input_verified']\n"
			"assert js('edit.value') == '' and js('window.pastes') == 0",
		)
	finally:
		await r.close()


async def test_nested_frame_and_no_selection_change(daemon, tmp_path, frame_site):  # noqa: F811
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({frame_site + "/cross"!r}); wait_for_load()\n'
			"f=next(f for f in frame_list() if f['url'].endswith('/inner'))\n"
			"""frame_eval(f, "(()=>{window.pastes=0;edit.addEventListener('paste',e=>{e.preventDefault();window.pastes++;edit.value+=e.clipboardData.getData('text/plain')});edit.value='existing:'})()")""",
		)
		await cell(
			r,
			"assert dispatch_paste('#edit', 'append', frame=f)['status'] == 'dispatched'\n"
			"assert frame_eval(f, 'edit.value') == 'existing:append'\n"
			"assert frame_eval(f, 'window.pastes') == 1\nassert js('document.title') == 'top'",
		)
	finally:
		await r.close()


async def test_rejected_target_and_ambiguous_receipt_no_retry(daemon, tmp_path, editor_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(r, f'new_tab({editor_site!r}); wait_for_load()')
		await cell(
			r,
			"assert dispatch_paste('#missing', 'x')['status'] == 'not_dispatched'\n"
			"js('edit.disabled=true')\nassert dispatch_paste('#edit','x')['status']=='not_dispatched'\n"
			"js('edit.disabled=false')\nimport browser_harness.helpers as h\noriginal=h.cdp\n"
			'def lost_receipt(method, *a, **kw):\n'
			'    result=original(method, *a, **kw)\n'
			"    if 'target.dispatchEvent' in kw.get('functionDeclaration',''): raise TimeoutError('receipt lost')\n"
			'    return result\nh.cdp=lost_receipt',
		)
		out = await r.call('exec', "dispatch_paste('#edit', 'exactly once')", 30)
		assert 'outcome_unknown' in out['error'] and 'receipt lost' in out['error']
		await cell(r, "h.cdp=original\nassert js('window.pastes')==1\nassert js('saved.textContent')=='exactly once'")
	finally:
		await r.close()


async def test_two_browser_sessions_keep_paste_payloads_separate(tmp_path, editor_site, chrome_binary):
	async def one(name):
		browser = Browser('chromium', headless=True, executable_path=chrome_binary)
		r = None
		try:
			r = Repl(tmp_path / name, await browser.start())
			await cell(
				r,
				f'new_tab({editor_site!r}); wait_for_load()\n'
				f"text={name!r}*20000\nassert dispatch_paste('#edit',text)['status']=='dispatched'\n"
				"assert js('saved.textContent')==text and js('window.pastes')==1",
			)
		finally:
			if r:
				await r.close()
			await browser.stop()

	await asyncio.gather(one('alpha'), one('beta'))


def test_payload_limit_before_browser_access():
	from browser_use.repl.paste import dispatch_paste

	with pytest.raises(ValueError, match='1 MiB'):
		dispatch_paste('#edit', 'a' * (1024 * 1024 + 1))


async def test_transfer_failure_never_dispatches_partial_text(daemon, tmp_path, editor_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({editor_site!r}); wait_for_load()\n'
			'import browser_harness.helpers as h\noriginal=h.cdp\n'
			'def fail_chunk(method, *a, **kw):\n'
			'    result=original(method, *a, **kw)\n'
			"    if 'this[name] += chunk' in kw.get('functionDeclaration',''): raise TimeoutError('chunk transfer interrupted')\n"
			'    return result\nh.cdp=fail_chunk',
		)
		out = await r.call('exec', "dispatch_paste('#edit', 'a'*100000)", 30)
		assert 'not_dispatched' in out['error'] and 'chunk transfer interrupted' in out['error']
		await cell(r, "h.cdp=original\nassert js('window.pastes')==0\nassert js('saved.textContent')==''")
	finally:
		await r.close()


async def test_replaced_editor_during_transfer_does_not_receive_paste(daemon, tmp_path, editor_site):
	r = Repl(tmp_path, daemon)
	try:
		await cell(
			r,
			f'new_tab({editor_site!r}); wait_for_load()\n'
			'import browser_harness.helpers as h\nraw = h.cdp\nreplaced = False\n'
			'def replace_during_transfer(method, *a, **kw):\n'
			'    global replaced\n'
			'    result = raw(method, *a, **kw)\n'
			"    if 'this[name] += chunk' in kw.get('functionDeclaration', '') and not replaced:\n"
			'        replaced = True\n'
			"""        raw('Runtime.evaluate', expression="window.oldEdit=edit; const replacement=edit.cloneNode(); replacement.addEventListener('paste',e=>{e.preventDefault();window.pastes++;saved.textContent=e.clipboardData.getData('text/plain')}); edit.replaceWith(replacement)")
"""
			'    return result\nh.cdp = replace_during_transfer',
		)
		await cell(
			r,
			"receipt = dispatch_paste('#edit', 'a'*100000)\nh.cdp = raw\n"
			"assert replaced and receipt['status'] == 'not_dispatched', receipt\n"
			"assert js('window.pastes') == 0\nassert js('saved.textContent') == ''\n"
			"assert js('oldEdit.isConnected') is False\nassert js('edit.value') == ''",
		)
	finally:
		await r.close()
