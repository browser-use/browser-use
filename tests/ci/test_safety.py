"""Opt-in file guards and audit evidence, using only local Chrome and HTTP."""

import base64
import html
import http.server
import json
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
	monkeypatch.setenv('BROWSER_USE_BLOCK_DOWNLOADS', '1')
	monkeypatch.setenv('BROWSER_USE_BLOCK_UPLOADS', 'true')
	monkeypatch.setattr(cli, '_run_mcp_stdio_server', lambda module, **options: launched.append(options))
	cli._run_cli_mcp_server()
	assert launched == [options]
	server = CLIMCPServer(**options)  # --cli-mcp flags also select a guarded Chromium.
	assert server._browser is not None and server._browser.kind == 'chromium'
	for code in (
		'upload_file("#file", "missing")',
		'cdp("DOM.setFileInputFiles", files=["missing"])',
		'cdp("Browser.setDownloadBehavior", behavior="allow")',
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


@pytest.mark.parametrize('secret', ['a', 'REDACTED', 'abc', '[***]'])
def test_audit_preserves_schema_and_redacts_values_once(tmp_path, secret):
	log = tmp_path / 'audit.jsonl'
	audit = AuditLog(log, {'x': secret})
	audit.write('action', secret, text=secret + 'ction', nested={secret: [secret, {secret: secret}]})
	record = read_audit(log)[0]
	assert set(record) == {'ts', 'event', 'target_id', 'text', 'nested'}
	assert record['event'] == 'action'
	marker = record['target_id']
	assert secret not in marker
	assert record['text'] == marker + 'ction'
	assert record['nested'] == {secret: [marker, {secret: marker}]}


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
			with pytest.raises(PermissionError, match=r'Download navigation refused \(block_downloads=True\)'):
				navigate(site + '/download')
	finally:
		await browser.stop()
