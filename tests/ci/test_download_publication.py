"""A completed Chrome file must have its stable name before downloads() exposes it."""

from pathlib import Path

import pytest

from browser_use import Browser, utils
from browser_use.browser import local
from browser_use.repl import worker


@pytest.mark.parametrize('finisher', ['worker', 'stop'])
@pytest.mark.parametrize(
	'name',
	['invoice.csv', '00000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', None, 'unusable.csv'],
)
async def test_downloads_publish_only_after_final_naming(tmp_path, monkeypatch, finisher, name):
	workspace = tmp_path
	state = workspace / '.browser-use'
	state.mkdir()
	monkeypatch.setattr(worker, 'STATE', state)
	monkeypatch.delenv('BU_REMOTE_BROWSER', raising=False)
	browser = Browser('chromium')
	browser._local = local.LocalBrowser()
	browser._downloads_dir = workspace / 'downloads'
	commands = []

	def cdp(method, *args, **params):
		commands.append((method, params))
		return {'sessionId': 'downloads'}

	monkeypatch.setattr(browser, '_cdp', lambda: cdp)
	browser._send_downloads(browser._downloads_dir)
	staging = Path(next(p['downloadPath'] for m, p in commands if m == 'Browser.setDownloadBehavior'))
	guid = '11111111-1111-4111-8111-111111111111'
	before = []
	if name == 'invoice.csv':
		(browser._downloads_dir / name).write_bytes(b'old')
		before = [{'name': name, 'size': 3}]
	(staging / guid).write_bytes(b'report')
	# Deterministic ordering: the file exists, but no completion handler has run yet.
	assert await browser.list_downloads() == before
	if name == 'unusable.csv':
		file_names = utils.file_names
		monkeypatch.setattr(
			utils,
			'file_names',
			lambda directory, base: iter([directory / 'missing' / base]) if base == name else file_names(directory, base),
		)
	begin = {'method': 'Browser.downloadWillBegin', 'params': {'guid': guid, 'suggestedFilename': name}}
	done = {'method': 'Browser.downloadProgress', 'params': {'guid': guid, 'state': 'completed'}}
	if finisher == 'worker':
		worker.CellStats().observe([begin, done])
	else:
		from browser_use.browser import browser as module

		monkeypatch.setattr(module, '_daemon_request', lambda *args: {'events': [begin, done]})
		assert await browser._finish_downloads() == 1
	expected = 'invoice (1).csv' if name == 'invoice.csv' else guid if name in (None, 'unusable.csv') else name
	assert await browser.list_downloads() == sorted([*before, {'name': expected, 'size': 6}], key=lambda f: f['name'])
	assert (browser._downloads_dir / expected).read_bytes() == b'report'
	assert not (staging / guid).exists()
