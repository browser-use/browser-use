"""A completed Chrome file must have its stable name before downloads() exposes it."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_use import Browser, utils
from browser_use.browser import local
from browser_use.repl import worker


@pytest.mark.parametrize(
	'finisher', ['worker', 'stop', 'lost_done', 'other_workspace', 'unannounced', 'canceled_stop', 'dead_stop']
)
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
	if finisher in ('worker', 'other_workspace'):
		worker.CellStats().observe([begin, done])
		if finisher == 'other_workspace':
			browser._downloads_dir = workspace / 'next' / 'downloads'
			browser._downloads_dir.mkdir(parents=True)
			assert await browser.list_downloads() == []  # late files belong to the earlier workspace
			browser._downloads_dir = workspace / 'downloads'
	elif finisher in ('canceled_stop', 'dead_stop'):
		from browser_use.browser import browser as module

		worker.CellStats().observe([begin, done])
		browser.name = 'publication-test-no-daemon'
		monkeypatch.setattr(module, '_shutdown_daemon', lambda *args: True)
		monkeypatch.setattr(browser._local, 'stop', lambda: None)
		if finisher == 'dead_stop':
			browser._local.proc = SimpleNamespace(poll=lambda: 0)
			await browser._stop()
		else:

			async def cancel_then_stop():
				asyncio.current_task().cancel()
				try:
					await asyncio.sleep(0)
				except asyncio.CancelledError:
					await browser._stop()

			await asyncio.create_task(cancel_then_stop())
		assert browser._local is None
	else:
		from browser_use.browser import browser as module

		if finisher == 'lost_done':
			worker.CellStats().observe([begin])  # the worker drained completion, then was closed before recording it
		monkeypatch.setattr(module, 'DOWNLOADS_TIMEOUT_S', 0)
		monkeypatch.setattr(module, '_daemon_request', lambda *args: {'events': [begin, done] if finisher == 'stop' else []})
		(staging / 'pending.crdownload').write_bytes(b'partial')
		assert await browser._finish_downloads() == (0 if finisher == 'unannounced' else 1)
		if finisher == 'unannounced':
			browser._publish_local_downloads(stopping=True)  # fallback only in the final shutdown scan
	expected = (
		guid
		if finisher == 'unannounced' or name in (None, 'unusable.csv')
		else 'invoice (1).csv'
		if name == 'invoice.csv'
		else name
	)
	assert await browser.list_downloads() == sorted([*before, {'name': expected, 'size': 6}], key=lambda f: f['name'])
	assert (browser._downloads_dir / expected).read_bytes() == b'report'
	assert not (staging / guid).exists()
	worker.CellStats().observe([begin, done])  # delayed/repeated events never rename a published path or add a suffix
	assert await browser.list_downloads() == sorted([*before, {'name': expected, 'size': 6}], key=lambda f: f['name'])


@pytest.mark.parametrize('failure', ['mkdir', 'publish', 'unlink', 'enumerate'])
async def test_unwritable_old_workspace_does_not_block_current_downloads(tmp_path, monkeypatch, failure):
	first, current = tmp_path / 'first', tmp_path / 'current'
	for workspace, guid, content in ((first, 'first-guid', b'first'), (current, 'current-guid', b'current')):
		staging = workspace / '.browser-use' / 'downloads'
		staging.mkdir(parents=True)
		(workspace / 'downloads').mkdir()
		(staging / guid).write_bytes(content)
		(workspace / '.browser-use' / 'downloads.jsonl').write_text(
			f'{{"guid":"{guid}","name":"report.txt"}}\n{{"done":"{guid}","state":"completed"}}\n', encoding='utf-8'
		)
	browser = Browser('chromium')
	browser._local = local.LocalBrowser()
	browser.note_downloads(first / '.browser-use' / 'downloads.jsonl')
	browser._downloads_dir = current / 'downloads'
	blocked = True
	if failure == 'enumerate':
		iterate = Path.iterdir

		def entries(path):
			if blocked and path == first / '.browser-use' / 'downloads':
				raise PermissionError('old staging directory is unreadable')
			return iterate(path)

		monkeypatch.setattr(Path, 'iterdir', entries)
	elif failure == 'mkdir':
		(first / 'downloads').rmdir()
		mkdir = Path.mkdir

		def create(path, *args, **kwargs):
			if blocked and path == first / 'downloads':
				raise PermissionError('old workspace is read-only')
			return mkdir(path, *args, **kwargs)

		monkeypatch.setattr(Path, 'mkdir', create)
	elif failure == 'unlink':
		unlink = Path.unlink

		def remove(path, *args, **kwargs):
			if blocked and path == first / '.browser-use' / 'downloads' / 'first-guid':
				raise PermissionError('old staging cleanup is read-only')
			return unlink(path, *args, **kwargs)

		monkeypatch.setattr(Path, 'unlink', remove)
	else:
		link, open_file = utils.os.link, utils.os.open

		def denied(path):
			if blocked and Path(path).parent == first / 'downloads':
				raise PermissionError('old workspace is read-only')

		def claim(source, destination, *args, **kwargs):
			denied(destination)
			return link(source, destination, *args, **kwargs)

		def create_file(path, *args, **kwargs):
			denied(path)
			return open_file(path, *args, **kwargs)

		monkeypatch.setattr(utils.os, 'link', claim)
		monkeypatch.setattr(utils.os, 'open', create_file)
	assert await browser.list_downloads() == [{'name': 'report.txt', 'size': 7}]
	assert (current / 'downloads' / 'report.txt').read_bytes() == b'current'
	assert (first / '.browser-use' / 'downloads' / 'first-guid').read_bytes() == b'first'
	if failure == 'unlink':
		assert 'first-guid' in browser._published_downloads  # the public hard link already committed
		assert (first / 'downloads' / 'report.txt').read_bytes() == b'first'
		assert await browser.list_downloads() == [{'name': 'report.txt', 'size': 7}]
		assert [path.name for path in (first / 'downloads').iterdir()] == ['report.txt']
	else:
		assert 'first-guid' not in browser._published_downloads
	blocked = False
	if failure == 'unlink':
		# A later Browser can also recover the retained hard link without allocating a new suffix.
		browser = Browser('chromium')
		browser._local = local.LocalBrowser()
		browser.note_downloads(first / '.browser-use' / 'downloads.jsonl')
		browser._downloads_dir = current / 'downloads'
	assert await browser.list_downloads() == [{'name': 'report.txt', 'size': 7}]
	assert (first / 'downloads' / 'report.txt').read_bytes() == b'first'
	assert not (first / '.browser-use' / 'downloads' / 'first-guid').exists()
	assert [path.name for path in (first / 'downloads').iterdir()] == ['report.txt']
	assert [path.name for path in (current / 'downloads').iterdir()] == ['report.txt']


async def test_stop_defers_unknown_names_until_final_shutdown_scan(tmp_path, monkeypatch):
	from browser_use.browser import browser as module

	staging = tmp_path / '.browser-use' / 'downloads'
	staging.mkdir(parents=True)
	(staging / 'late-guid').write_bytes(b'report')
	browser = Browser('chromium')
	browser._local = local.LocalBrowser()
	browser._downloads_dir = tmp_path / 'downloads'
	browser.note_downloads(staging.parent / 'downloads.jsonl')
	monkeypatch.setattr(module, '_daemon_request', lambda *args: {'events': []})
	assert await browser._finish_downloads() == 0
	assert (staging / 'late-guid').read_bytes() == b'report'
	assert 'late-guid' not in browser._published_downloads
	# The worker records the begin after the poll, before the final shutdown scan.
	monkeypatch.setattr(worker, 'STATE', staging.parent)
	worker.CellStats().observe(
		[{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'late-guid', 'suggestedFilename': 'report.txt'}}]
	)
	browser._publish_local_downloads(stopping=True)
	assert await browser.list_downloads() == [{'name': 'report.txt', 'size': 6}]
	assert not (staging / 'late-guid').exists()


@pytest.mark.parametrize('alias', ['file', 'directory'])
def test_download_link_recovery_preserves_symlink_aliases(tmp_path, alias):
	staging, public = tmp_path / 'staging', tmp_path / 'downloads'
	staging.mkdir()
	public.mkdir()
	source = staging / 'report.txt'
	source.write_bytes(b'report')
	try:
		if alias == 'file':
			(public / 'report.txt').symlink_to(source)
		else:
			(public / 'alias').symlink_to(staging, target_is_directory=True)
	except OSError as e:
		pytest.skip(f'symlink creation unavailable: {e}')
	if alias == 'file':
		published = utils.publish_download(source, 'report.txt', public)
		assert published == public / 'report (1).txt'
		assert published.read_bytes() == b'report' and not published.is_symlink()
		assert (public / 'report.txt').is_symlink()  # never reused as the destination or overwritten
	else:
		published = utils.name_download(source, source.name, public / 'alias')
		assert published == public / 'alias' / source.name
		assert source.read_bytes() == published.read_bytes() == b'report'  # the same entry must not be unlinked
