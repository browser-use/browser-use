"""Opt-in file guards and audit evidence, using only local Chrome and HTTP."""

import base64
import html
import http.server
import json
import logging
import os
import stat
import threading
import urllib.parse

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.audit import AuditLog
from browser_use.domains import DomainRules, Guard
from browser_use.repl.session import Repl


class Site(http.server.BaseHTTPRequestHandler):
	def log_message(self, *args):
		pass

	def do_GET(self):
		self.send_response(200)
		if self.path.startswith('/download'):
			self.send_header('Content-Disposition', 'attachment; filename="evidence.txt"')
			self.send_header('Content-Type', 'application/octet-stream')
			body = b'download evidence'
		else:
			self.send_header('Content-Type', 'text/html')
			body = b'<input id=text><input id=password type=password><input id=file type=file><a id=download href=/download>Download</a>'
		self.end_headers()
		self.wfile.write(body)


@pytest.fixture
def site():
	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Site)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	yield f'http://127.0.0.1:{server.server_port}'
	server.shutdown()
	server.server_close()
	thread.join()


def read_audit(path):
	return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize('blocked', [True, False])
async def test_browser_download_guard_and_audit_preserve_download_behavior(chrome, daemon, site, tmp_path, blocked):
	from browser_use.browser.browser import _daemon_cdp

	dest = tmp_path / 'downloads'
	dest.mkdir()
	_daemon_cdp(daemon['BU_NAME'], 'Browser.setDownloadBehavior', behavior='allow', downloadPath=str(dest))
	log = tmp_path / 'audit.jsonl'
	guard = Guard(chrome['ws'], DomainRules(), block_downloads=blocked, audit=AuditLog(log))
	guard.start()
	repl = Repl(tmp_path, daemon)  # Deliberately no helper restrictions: the browser must deny the download.
	try:
		r = await repl.call(
			'exec', f'goto_url({site!r}); wait_for_load(); js("document.querySelector(\'#download\').click()"); wait(1)', 30
		)
		assert r['error'] is None, r
		if blocked:
			assert not list(dest.iterdir())
		else:
			assert (dest / 'evidence.txt').read_bytes() == b'download evidence'
		event = 'download_blocked' if blocked else 'download_completed'
		assert any(e['event'] == event and e['target_id'] for e in read_audit(log))
	finally:
		await repl.close()
		guard.close()
		_daemon_cdp(daemon['BU_NAME'], 'Browser.setDownloadBehavior', behavior='default')


async def test_worker_refuses_upload_and_download_helpers(daemon, site, tmp_path):
	repl = Repl(tmp_path, {**daemon, 'BU_BLOCK_UPLOADS': '1', 'BU_BLOCK_DOWNLOADS': '1'})
	try:
		for code, flag in (
			('upload_file("#file", "nonexistent.txt")', 'block_uploads'),
			('cdp("DOM.setFileInputFiles", files=["nonexistent.txt"], backendNodeId=1)', 'block_uploads'),
			('cdp("Browser.setDownloadBehavior", behavior="allow", downloadPath="/tmp")', 'block_downloads'),
			('cdp("Page.setDownloadBehavior", behavior="allow", downloadPath="/tmp")', 'block_downloads'),
			(f'http_get({site + "/download"!r})', 'block_downloads'),
		):
			r = await repl.call('exec', code, 30)
			assert r['error'] and 'PermissionError:' in r['error'] and flag in r['error'], r
	finally:
		await repl.close()


async def test_file_chooser_is_intercepted(chrome, daemon, site, tmp_path):
	log = tmp_path / 'audit.jsonl'
	guard = Guard(chrome['ws'], DomainRules(), block_uploads=True, audit=AuditLog(log))
	guard.start()
	repl = Repl(tmp_path, daemon)
	try:
		r = await repl.call(
			'exec',
			f'new_tab({site!r}); wait_for_load(); wait(.3); cdp("Runtime.evaluate", expression="document.querySelector(\'#file\').click()", userGesture=True); wait(.5); print(js("document.querySelector(\'#file\').files.length"))',
			30,
		)
		assert r['error'] is None and r['output'].strip().endswith('0'), r
		assert any(e['event'] == 'upload_blocked' and e['target_id'] for e in read_audit(log))
	finally:
		await repl.close()
		guard.close()


@pytest.mark.parametrize('audit', [False, True])
async def test_downloads_work_by_default_and_audit_completion(chrome_binary, site, tmp_path, audit):
	log = tmp_path / 'audit.jsonl'
	model, _ = script(
		(
			'python',
			{'code': f'goto_url({site!r}); wait_for_load(); js("document.querySelector(\'#download\').click()"); wait(1)'},
		),
		('finish', {'success': True, 'result': 'done'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, allowed_domains=['127.0.0.1'] if audit else None)
	if audit:
		await browser.start()  # Add auditing to an already-running domain guard.
	agent = Agent('Download the file', model, browser=browser, workspace=tmp_path, audit_log=log if audit else None)
	result = await agent.run()
	assert result.status == 'completed', result.error
	assert (tmp_path / 'downloads' / 'evidence.txt').read_bytes() == b'download evidence'
	assert not browser.block_downloads and not browser.block_uploads
	if audit:
		assert any(e['event'] == 'download_completed' and e['target_id'] for e in read_audit(log))
	else:
		assert not log.exists()


async def test_agent_audit_masks_secrets_passwords_and_url_credentials(chrome_binary, site, tmp_path):
	secret = 'sensitive-value-7319'
	password = 'password-field-value'
	log = tmp_path / 'audit.jsonl'
	model, _ = script(
		(
			'python',
			{
				'code': f'goto_url({site + "/?token=oauth-token-value"!r}); wait_for_load(); fill_input("#text", "public text"); fill_input("#text", ""); js("document.querySelector(\'#text\').focus()"); type_secret("credential"); checkpoint("typed.json", js("document.querySelector(\'#text\').value") == {secret!r}); fill_input("#password", {password!r}); js("location.hash = \'changed\'"); wait(.3)'
			},
		),
		('python', {'code': 'upload_file("#file", "missing.txt")'}),
		('python', {'code': f'http_get({site + "/download"!r})'}),
		('python', {'code': f'goto_url({site.replace("127.0.0.1", "localhost")!r})'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	browser = Browser(
		'chromium',
		headless=True,
		executable_path=chrome_binary,
		allowed_domains=['127.0.0.1'],
		block_uploads=True,
		block_downloads=True,
	)
	agent = Agent('Browse', model, browser=browser, workspace=tmp_path, audit_log=log, sensitive_data={'credential': secret})
	result = await agent.run()
	assert result.status == 'completed', result.error
	assert json.loads((tmp_path / 'typed.json').read_text()) is True
	text = log.read_text()
	assert all(value not in text for value in (secret, password, 'oauth-token-value'))
	assert 'public text' in text
	events = read_audit(log)
	assert {'navigation', 'action', 'upload_blocked', 'download_blocked', 'navigation_blocked'} <= {e['event'] for e in events}
	assert any(e.get('helper') == 'type_secret' for e in events)
	assert any(e['event'] == 'navigation' and '#changed' in e['url'] for e in events)
	assert all(isinstance(e['ts'], float) and 'target_id' in e for e in events)


def test_remote_upload_refuses_before_reading_or_sending(tmp_path):
	from browser_use.remote_upload import set_files, uploader

	def cdp(*args, **kwargs):
		pytest.fail('blocked upload contacted the browser')

	with pytest.raises(PermissionError, match='block_uploads=True'):
		set_files(cdp, 'object', tmp_path / 'absent', remote=True, blocked=True)
	with pytest.raises(PermissionError, match='block_uploads=True'):
		uploader(cdp, lambda: True, blocked=lambda: True)('#file', tmp_path / 'absent')


def test_mcp_file_flags_config_and_helper_refusals(tmp_path, monkeypatch):
	from browser_use.cli import _mcp_browser_options
	from browser_use.mcp.cli_mcp import CLIMCPServer

	config = tmp_path / 'config.json'
	config.write_text(
		json.dumps({'browser_profile': {'default': {'default': True, 'block_downloads': True, 'block_uploads': True}}})
	)
	monkeypatch.setenv('BROWSER_USE_CONFIG_PATH', str(config))
	options = _mcp_browser_options()
	assert options == {'block_downloads': True, 'block_uploads': True}
	from browser_use import cli

	launched = []
	monkeypatch.setenv('BROWSER_USE_BLOCK_DOWNLOADS', ' 1')
	monkeypatch.setenv('BROWSER_USE_BLOCK_UPLOADS', ' YES ')
	monkeypatch.setattr(cli, '_run_mcp_stdio_server', lambda module, **options: launched.append(options))
	cli._run_cli_mcp_server()
	assert launched == [options]
	server = CLIMCPServer(**options)  # --cli-mcp flags also select a guarded Chromium.
	assert server._browser is not None and server._browser.kind == 'chromium'
	for code in (
		'upload_file("#file", "missing")',
		'cdp("DOM.setFileInputFiles", files=["missing"])',
		'cdp("Browser.setDownloadBehavior", behavior="allow")',
		'cdp("Page.setDownloadBehavior", behavior="allow")',
	):
		out, failed = server._execute(code, connect=False)
		assert failed and 'PermissionError:' in out, out


async def test_cdp_url_browser_applies_file_flags(chrome, site, tmp_path):
	browser = Browser(cdp_url=chrome['http'], block_downloads=True, block_uploads=True)
	env = await browser.start()
	try:
		assert env['BU_BLOCK_UPLOADS'] == env['BU_BLOCK_DOWNLOADS'] == '1'
		assert browser._guard is not None
		with pytest.raises(PermissionError, match='block_downloads=True'):
			await browser.download_files(tmp_path)
	finally:
		await browser.stop()


@pytest.mark.parametrize('secret', ['a', 'ab', 'abc', '<&', 'long-secret'])
def test_audit_redacts_all_encodings_for_every_secret_length(tmp_path, secret):
	forms = {
		secret,
		secret.lower(),
		secret.upper(),
		secret[::-1],
		base64.b64encode(secret.encode()).decode(),
		base64.b64encode(secret.encode()).decode().rstrip('='),
		base64.urlsafe_b64encode(secret.encode()).decode(),
		secret.encode().hex(),
		secret.encode().hex().upper(),
		urllib.parse.quote(secret, safe=''),
		urllib.parse.quote_plus(secret),
		json.dumps(secret)[1:-1],
		repr(secret)[1:-1],
		html.escape(secret),
	}
	log = tmp_path / 'audit.jsonl'
	audit = AuditLog(log, {'x': secret})
	for form in forms:
		audit.write('action', text=form)
	for record in read_audit(log):
		assert all(form not in record['text'] for form in forms)


@pytest.mark.parametrize('secret', ['abc', 'long-secret'])
def test_audit_preserves_schema_and_redacts_values_once(tmp_path, secret):
	log = tmp_path / 'audit.jsonl'
	audit = AuditLog(log, {'x': secret})
	audit.write('action', 'tab', text=secret + 'ction', nested={secret: [secret, {secret: secret}]})
	record = read_audit(log)[0]
	assert set(record) == {'ts', 'event', 'target_id', 'text', 'nested'}
	assert record['event'] == 'action'
	assert record['target_id'] == 'tab'
	marker = '[REDACTED]'
	assert record['text'] == marker + 'ction'
	assert record['nested'] == {marker: [marker, {marker: marker}]}


async def test_mcp_download_navigation_raises_permission_error(chrome, daemon, site, monkeypatch):
	from browser_harness import helpers

	monkeypatch.setattr(helpers, 'NAME', daemon['BU_NAME'])
	from browser_use.mcp.cli_mcp import CLIMCPServer

	browser = Browser(cdp_url=chrome['http'], block_downloads=True)
	await browser.start()
	server = CLIMCPServer(block_downloads=True)
	server._browser = browser
	try:
		ns = server._ensure_namespace()
		assert ns['goto_url'](site).get('errorText') is None
		for navigate in (lambda url: ns['goto_url'](url), lambda url: ns['cdp']('Page.navigate', url=url)):
			with pytest.raises(PermissionError, match=r'Navigation aborted .*block_downloads=True'):
				navigate(site + '/download')
	finally:
		await browser.stop()


@pytest.mark.parametrize(
	('secrets', 'text'),
	[
		({'s': 'REDACTED', 't': '['}, 'R[EDACTED'),
		({'s': 'x[REDACTED]y', 't': '!'}, 'x!y'),
		({'s': '[', 't': '*'}, 'before [ * after'),
	],
)
def test_audit_falls_back_for_unsafe_markers_and_substitution_results(tmp_path, secrets, text, monkeypatch):
	monkeypatch.setattr('browser_use.audit.time.time', lambda: 1700000000.0)
	log = tmp_path / 'audit.jsonl'
	audit = AuditLog(log, secrets)
	audit.write('action', text=text, nested={text: [text]})
	if 'REDACTED' in secrets.values():  # The fallback schema's redacted key also matches.
		assert read_audit(log) == []
		return
	record = read_audit(log)[0]
	assert record == {'ts': record['ts'], 'event': 'action', 'target_id': None, 'redacted': True}
	assert not audit.pattern.search(log.read_text())


@pytest.mark.parametrize('one_shot', [False, True])
@pytest.mark.parametrize('text', ['%c3%bf', '%C3%bF', 'c3bF'])
def test_audit_matches_case_insensitive_encodings(tmp_path, text, one_shot):
	log = tmp_path / 'audit.jsonl'
	audit = AuditLog(log, iter([('s', 'ÿ')]) if one_shot else {'s': 'ÿ'})
	audit.write('action', text=text)
	assert read_audit(log)[0]['text'] == '[REDACTED]'


def test_audit_redacts_unicode_case_forms(tmp_path):
	audit = AuditLog(tmp_path / 'audit.jsonl', {'s': 'ÿsecret'})
	audit.write('action', text='ŸSECRET')
	assert read_audit(audit.path)[0]['text'] == '[REDACTED]'
	assert not audit.pattern.search(audit.path.read_text(encoding='utf-8'))


def test_aborted_navigation_does_not_claim_a_download():
	from browser_use.repl.worker import _download_navigation_result

	with pytest.raises(PermissionError, match='Navigation aborted') as error:
		_download_navigation_result({'errorText': 'net::ERR_ABORTED'}, blocked=True)
	assert 'Download navigation refused' not in str(error.value)


@pytest.mark.parametrize('failure', ['short', 'error'])
def test_audit_write_failure_disables_later_appends(tmp_path, monkeypatch, caplog, failure):
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	audit = AuditLog(tmp_path / 'audit.jsonl')
	write = os.write
	calls = []

	def partial_write(fd, data):
		calls.append(data)
		written = write(fd, data[:3])
		if failure == 'error':
			raise OSError('private contents')
		return written

	monkeypatch.setattr(os, 'write', partial_write)
	audit.write('action', text='private contents')
	audit.write('action', text='next record')
	audit.write('action', text='another record')
	assert len(calls) == 1
	assert audit.path.stat().st_size == 3
	assert caplog.text.count('Audit record could not be written') == 1
	assert 'private contents' not in caplog.text


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permissions')
@pytest.mark.parametrize('existing', [False, True])
def test_audit_file_is_private(tmp_path, existing):
	path = tmp_path / 'audit.jsonl'
	if existing:
		path.touch(mode=0o644)
	audit = AuditLog(path)
	assert stat.S_IMODE(audit.path.stat().st_mode) == 0o600


@pytest.mark.parametrize('failure', ['io', 'serialization', 'zero_write'])
def test_audit_failures_do_not_prevent_enforcement(tmp_path, monkeypatch, failure):
	audit = AuditLog(tmp_path / 'audit.jsonl')
	if failure == 'io':
		monkeypatch.setattr(os, 'open', lambda *a, **kw: (_ for _ in ()).throw(OSError('disk full')))
	elif failure == 'zero_write':
		monkeypatch.setattr(os, 'write', lambda *a: 0)
	else:
		audit.write('action', text=object())
	guard = Guard('unused', DomainRules.of(['allowed.test']), audit=audit)
	sent = []
	monkeypatch.setattr(guard, '_send', lambda method, *a, **kw: sent.append(method))
	guard.pages['tab'] = 'about:blank'
	guard._handle(
		{
			'method': 'Fetch.requestPaused',
			'params': {'frameId': 'tab', 'requestId': 'r', 'request': {'url': 'https://blocked.test'}},
		}
	)
	guard._reset('tab', 'https://blocked.test', 'blocked')
	assert sent == ['Fetch.failRequest', 'Target.attachToTarget']


def test_runtime_tab_setup_failure_keeps_guard_connected():
	guard = Guard('unused', DomainRules())
	guard._ready.set()
	guard._setup.add(1)
	guard._handle({'id': 1, 'error': {'message': 'target closed'}})
	assert not guard._setup


@pytest.mark.parametrize('method', ['Target.detachedFromTarget', 'Target.targetDestroyed'])
def test_guard_discards_frames_for_closed_targets(method):
	guard = Guard('unused', DomainRules())
	guard.sessions = {'session': 'tab'}
	guard.frames = {'main': 'tab', 'child': 'tab', 'other': 'other-tab'}
	guard._handle({'method': method, 'params': {'sessionId': 'session', 'targetId': 'tab'}})
	assert guard.frames == {'other': 'other-tab'}


@pytest.mark.parametrize('name', ['block_downloads', 'block_uploads'])
@pytest.mark.parametrize('value', ['false', 1, None])
def test_file_flags_require_bools(name, value):
	with pytest.raises(TypeError, match=name):
		Browser(**{name: value})


@pytest.mark.parametrize('path', ['', '.'])
def test_agent_rejects_invalid_audit_path(path):
	model, _ = script(('finish', {'success': True, 'result': 'done'}))
	with pytest.raises(ValueError, match='audit_log'):
		Agent('Browse', model, audit_log=path)


def test_repl_preserves_positional_arguments(tmp_path):
	async def reattach():
		pass

	repl = Repl(tmp_path, {}, 'default', {}, reattach)
	assert repl.reattach is reattach
	assert repl.audit_log is None


@pytest.mark.parametrize('details', [{'value': 1234}, {'nested': {1234: 'safe'}}])
def test_audit_drops_details_with_numeric_secret(tmp_path, details, monkeypatch):
	monkeypatch.setattr('browser_use.audit.time.time', lambda: 1700000000.0)
	audit = AuditLog(tmp_path / 'audit.jsonl', {'s': '1234'})
	audit.write('action', 'tab', **details)
	record = read_audit(audit.path)[0]
	assert record == {'ts': record['ts'], 'event': 'action', 'target_id': 'tab', 'redacted': True}


def test_audit_null_key_cannot_leak_secret(tmp_path):
	audit = AuditLog(tmp_path / 'audit.jsonl', {'s': 'null', 'one': '[', 'two': '*'})
	audit.write('action', 'page', nested={'[': 'safe'})
	record = read_audit(audit.path)[0]
	assert record == {'ts': record['ts'], 'event': 'action', 'target_id': 'page', 'redacted': True}
	assert 'null' not in audit.path.read_text()


@pytest.mark.parametrize(
	('secret', 'target_id', 'expected_target'),
	[
		('tion', 'tab', 'tab'),
		('1700000000', 'tab', 'tab'),
		('ts', 'tab', 'tab'),
		('event', 'tab', 'tab'),
		('private-id', 'private-id', '[REDACTED]'),
		('[', '[', None),
	],
)
def test_audit_preserves_fixed_fields_and_scrubs_target(tmp_path, monkeypatch, secret, target_id, expected_target):
	monkeypatch.setattr('browser_use.audit.time.time', lambda: 1700000000.0)
	audit = AuditLog(tmp_path / 'audit.jsonl', {'s': secret})
	audit.write('action', target_id, text='safe')
	record = read_audit(audit.path)[0]
	assert record['ts'] == 1700000000.0
	assert record['event'] == 'action'
	assert record['target_id'] == expected_target
	assert not audit.pattern.search(json.dumps({k: v for k, v in record.items() if k not in ('ts', 'event')}))


@pytest.mark.parametrize('secret', ['private', r'\ud800'])
def test_audit_preserves_lone_surrogates_and_checks_written_escapes(tmp_path, secret):
	audit = AuditLog(tmp_path / 'audit.jsonl', {'s': secret})
	audit.write('action', 'tab', text='before \ud800 private after')
	record = read_audit(audit.path)[0]
	assert record['event'] == 'action'
	if secret == 'private':
		assert record['text'] == 'before \ud800 [REDACTED] after'
	else:
		assert record['redacted'] is True
	assert not audit.pattern.search(audit.path.read_text(encoding='utf-8'))


@pytest.mark.parametrize(
	('block_uploads', 'failed_method'),
	[(False, 'Page.enable'), (True, 'Page.enable'), (True, 'Page.setInterceptFileChooserDialog')],
)
def test_tab_setup_failure_closes_only_upload_guarded_tab(monkeypatch, caplog, failed_method, block_uploads):
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	guard = Guard('unused', DomainRules(), block_uploads=block_uploads, block_downloads=True)
	guard._ready.set()
	sent = []

	class Socket:
		def send(self, data):
			sent.append(json.loads(data))

	guard._ws = Socket()
	guard._handle(
		{
			'method': 'Target.attachedToTarget',
			'params': {'sessionId': 'session', 'targetInfo': {'targetId': 'tab'}},
		}
	)
	failed = next(msg for msg in sent if msg['method'] == failed_method)
	guard._handle({'id': failed['id'], 'sessionId': 'session', 'error': {'message': 'setup refused'}})
	if block_uploads:
		assert sent[-1]['method'] == 'Target.closeTarget'
		assert sent[-1]['params'] == {'targetId': 'tab'}
		for pending in list(guard._setup):
			guard._handle({'id': pending, 'sessionId': 'session', 'result': {}})
		assert not any(msg['method'] == 'Runtime.runIfWaitingForDebugger' for msg in sent)
	else:
		assert sent[-1]['method'] == 'Runtime.runIfWaitingForDebugger'
		assert sent[-1]['sessionId'] == 'session'
	assert 'setup refused' in caplog.text
