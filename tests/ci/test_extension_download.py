import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.config import CONFIG

EXTENSION_IDS = [
	'ddkjiahejlhfcafbddmgiahcphecmpfh',
	'edibdbjcniadpccecjdfdjjppcpchdlm',
	'gidlfommnbibbmegmgajdbikelkdcmcl',
]


class _InterruptedResponseHandler(BaseHTTPRequestHandler):
	def do_GET(self) -> None:
		self.send_response(200)
		self.send_header('Content-Length', '100')
		self.end_headers()
		self.wfile.write(b'short')
		self.wfile.flush()
		self.close_connection = True

	def log_message(self, format: str, *args: object) -> None:
		pass


class _EmptyResponseHandler(BaseHTTPRequestHandler):
	def do_GET(self) -> None:
		self.send_response(200)
		self.send_header('Content-Length', '0')
		self.end_headers()

	def log_message(self, format: str, *args: object) -> None:
		pass


class _SuccessfulResponseHandler(BaseHTTPRequestHandler):
	payload = b'valid-extension-payload'

	def do_GET(self) -> None:
		self.send_response(200)
		self.send_header('Content-Length', str(len(self.payload)))
		self.end_headers()
		self.wfile.write(self.payload)

	def log_message(self, format: str, *args: object) -> None:
		pass


def _start_server(handler: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, threading.Thread]:
	server = HTTPServer(('127.0.0.1', 0), handler)
	thread = threading.Thread(target=server.handle_request, daemon=True)
	thread.start()
	return server, thread


def _stop_server(server: HTTPServer, thread: threading.Thread) -> None:
	server.server_close()
	thread.join(timeout=2)


def _create_valid_extracted_extension(cache_dir: Path, extension_id: str) -> None:
	extension_dir = cache_dir / extension_id
	extension_dir.mkdir(parents=True)
	(extension_dir / 'manifest.json').write_text(
		json.dumps({'manifest_version': 3, 'name': extension_id, 'version': '1'}), encoding='utf-8'
	)


def test_interrupted_extension_download_does_not_leave_cache_file(tmp_path: Path) -> None:
	server, thread = _start_server(_InterruptedResponseHandler)
	output_path = tmp_path / 'extension.crx'
	profile = BrowserProfile(enable_default_extensions=False)
	try:
		with pytest.raises(Exception, match='Failed to download extension'):
			profile._download_extension(f'http://127.0.0.1:{server.server_port}/extension.crx', output_path)
	finally:
		_stop_server(server, thread)

	assert not output_path.exists()


def test_empty_extension_download_does_not_leave_cache_file(tmp_path: Path) -> None:
	server, thread = _start_server(_EmptyResponseHandler)
	output_path = tmp_path / 'extension.crx'
	profile = BrowserProfile(enable_default_extensions=False)
	try:
		with pytest.raises(Exception, match='empty body'):
			profile._download_extension(f'http://127.0.0.1:{server.server_port}/extension.crx', output_path)
	finally:
		_stop_server(server, thread)

	assert not output_path.exists()


def test_successful_extension_download_writes_complete_body(tmp_path: Path) -> None:
	server, thread = _start_server(_SuccessfulResponseHandler)
	output_path = tmp_path / 'extension.crx'
	profile = BrowserProfile(enable_default_extensions=False)
	try:
		profile._download_extension(f'http://127.0.0.1:{server.server_port}/extension.crx', output_path)
	finally:
		_stop_server(server, thread)

	assert output_path.read_bytes() == _SuccessfulResponseHandler.payload


def test_empty_cached_extension_is_removed_before_redownload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'')

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	def fail_download(self: BrowserProfile, url: str, output_path: Path) -> None:
		assert not output_path.exists()
		raise Exception('stop after cache cleanup')

	monkeypatch.setattr(BrowserProfile, '_download_extension', fail_download)
	BrowserProfile(enable_default_extensions=True)._ensure_default_extensions_downloaded()

	assert not cached_crx.exists()


def test_stale_extension_download_temp_file_is_cleaned_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	for extension_id in EXTENSION_IDS:
		_create_valid_extracted_extension(cache_dir, extension_id)

	stale_temp = cache_dir / f'.{EXTENSION_IDS[0]}.crx.stale.tmp'
	recent_temp = cache_dir / f'.{EXTENSION_IDS[0]}.crx.recent.tmp'
	stale_temp.write_bytes(b'stale')
	recent_temp.write_bytes(b'recent')
	stale_timestamp = recent_temp.stat().st_mtime - 7200
	os.utime(stale_temp, (stale_timestamp, stale_timestamp))

	BrowserProfile(enable_default_extensions=True)._ensure_default_extensions_downloaded()

	assert not stale_temp.exists()
	assert recent_temp.exists()


def test_nonempty_corrupt_cached_extension_is_invalidated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'not-a-valid-crx-but-nonempty')

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	def unexpected_download(self: BrowserProfile, url: str, output_path: Path) -> None:
		raise AssertionError('existing non-empty cache should be extracted before any redownload')

	monkeypatch.setattr(BrowserProfile, '_download_extension', unexpected_download)
	BrowserProfile(enable_default_extensions=True)._ensure_default_extensions_downloaded()

	assert not cached_crx.exists()


def test_corrupt_cached_extension_is_redownloaded_on_next_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	import zipfile

	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'

	with zipfile.ZipFile(cached_crx, 'w', compression=zipfile.ZIP_STORED) as archive:
		archive.writestr('manifest.json', json.dumps({'manifest_version': 3, 'name': 'broken', 'version': '1'}))
		archive.writestr('later.bin', b'A' * 128)

	data = bytearray(cached_crx.read_bytes())
	payload_offset = data.find(b'A' * 128)
	assert payload_offset != -1
	data[payload_offset + 10] ^= 0xFF
	cached_crx.write_bytes(data)

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()

	extension_dir = cache_dir / EXTENSION_IDS[0]
	assert not cached_crx.exists()
	assert not extension_dir.exists()

	download_calls: list[Path] = []

	def write_valid_extension(self: BrowserProfile, url: str, output_path: Path) -> None:
		download_calls.append(output_path)
		with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as archive:
			archive.writestr('manifest.json', json.dumps({'manifest_version': 3, 'name': 'recovered', 'version': '1'}))

	monkeypatch.setattr(BrowserProfile, '_download_extension', write_valid_extension)
	paths = profile._ensure_default_extensions_downloaded()

	assert download_calls == [cached_crx]
	assert str(extension_dir) in paths


def test_filesystem_extraction_error_retries_preserved_cache_on_next_launch(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'cached-extension-data')

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	extract_calls = 0

	def retry_extract(self: BrowserProfile, crx_path: Path, extract_dir: Path) -> None:
		nonlocal extract_calls
		extract_calls += 1
		if extract_calls == 1:
			extract_dir.mkdir(parents=True, exist_ok=True)
			(extract_dir / 'partial.bin').write_bytes(b'partial')
			raise OSError('simulated filesystem extraction failure')
		if extract_dir.exists():
			import shutil

			shutil.rmtree(extract_dir)
		_create_valid_extracted_extension(cache_dir, EXTENSION_IDS[0])

	monkeypatch.setattr(BrowserProfile, '_extract_extension', retry_extract)
	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()

	extension_dir = cache_dir / EXTENSION_IDS[0]
	assert cached_crx.exists()
	assert not (extension_dir / 'manifest.json').exists()

	paths = profile._ensure_default_extensions_downloaded()

	assert extract_calls == 2
	assert str(extension_dir) in paths


def test_oserror_after_complete_extraction_retries_without_deleting_directory(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'cached-extension-data')

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	extract_calls = 0

	def extract_then_retry(self: BrowserProfile, crx_path: Path, extract_dir: Path) -> None:
		nonlocal extract_calls
		extract_calls += 1
		if not extract_dir.exists():
			_create_valid_extracted_extension(cache_dir, EXTENSION_IDS[0])
			(extract_dir / 'background.js').write_text('ok', encoding='utf-8')
		if extract_calls == 1:
			raise PermissionError('simulated post-extraction cleanup failure')

	monkeypatch.setattr(BrowserProfile, '_extract_extension', extract_then_retry)
	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()

	extension_dir = cache_dir / EXTENSION_IDS[0]
	extract_marker = cache_dir / f'.{EXTENSION_IDS[0]}.extracting'
	assert cached_crx.exists()
	assert (extension_dir / 'manifest.json').exists()
	assert (extension_dir / 'background.js').exists()
	assert extract_marker.exists()

	paths = profile._ensure_default_extensions_downloaded()

	assert extract_calls == 2
	assert str(extension_dir) in paths
	assert not extract_marker.exists()


def test_oserror_after_manifest_retries_instead_of_trusting_partial_directory(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'cached-extension-data')

	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	extract_calls = 0

	def fail_after_manifest_then_succeed(self: BrowserProfile, crx_path: Path, extract_dir: Path) -> None:
		nonlocal extract_calls
		extract_calls += 1
		if extract_dir.exists():
			import shutil

			shutil.rmtree(extract_dir)
		_create_valid_extracted_extension(cache_dir, EXTENSION_IDS[0])
		if extract_calls == 1:
			raise OSError('simulated disk failure after manifest')

	monkeypatch.setattr(BrowserProfile, '_extract_extension', fail_after_manifest_then_succeed)
	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()

	extension_dir = cache_dir / EXTENSION_IDS[0]
	extract_marker = cache_dir / f'.{EXTENSION_IDS[0]}.extracting'
	assert (extension_dir / 'manifest.json').exists()
	assert extract_marker.exists()

	paths = profile._ensure_default_extensions_downloaded()

	assert extract_calls == 2
	assert str(extension_dir) in paths
	assert not extract_marker.exists()


@pytest.mark.parametrize('failure_point', ['write', 'close'])
def test_crx_fallback_temp_zip_is_cleaned_when_temp_io_fails(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
	import io
	import tempfile
	import zipfile

	crx_path = tmp_path / 'extension.crx'
	extract_dir = tmp_path / 'extension'

	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
		archive.writestr('manifest.json', json.dumps({'manifest_version': 3, 'name': 'fallback', 'version': '1'}))
		archive.writestr('payload.bin', b'x' * 64)
	crx_path.write_bytes(b'Cr24' + (3).to_bytes(4, 'little') + (0).to_bytes(4, 'little') + buffer.getvalue())

	real_zip_file = zipfile.ZipFile

	def force_crx_fallback(file: str | Path, mode: Literal['r'] = 'r'):
		if str(file).endswith('.crx'):
			raise zipfile.BadZipFile('force CRX fallback')
		return real_zip_file(file, mode)

	created_temp = tmp_path / f'{failure_point}.zip'

	class FailingTempFile:
		def __init__(self) -> None:
			self._file = open(created_temp, 'w+b')
			self.name = str(created_temp)
			self._close_failed = False

		def __enter__(self):
			return self

		def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
			self.close()

		def write(self, data: bytes) -> int:
			if failure_point == 'write':
				self._file.write(data[:16])
				self._file.flush()
				raise OSError('simulated temp write failure')
			return self._file.write(data)

		def close(self) -> None:
			if not self._file.closed:
				self._file.close()
			if failure_point == 'close' and not self._close_failed:
				self._close_failed = True
				raise OSError('simulated temp close failure')

	def failing_named_temp_file(*args: object, **kwargs: object) -> FailingTempFile:
		return FailingTempFile()

	monkeypatch.setattr(zipfile, 'ZipFile', force_crx_fallback)
	monkeypatch.setattr(tempfile, 'NamedTemporaryFile', failing_named_temp_file)

	with pytest.raises(OSError, match=f'simulated temp {failure_point} failure'):
		BrowserProfile(enable_default_extensions=False)._extract_extension(crx_path, extract_dir)

	assert not created_temp.exists()


@pytest.mark.parametrize('crx_version', [2, 3])
@pytest.mark.parametrize(
	'manifest_contents',
	[
		None,
		'{invalid-json',
		'[]',
		'{}',
		'{"manifest_version":"3"}',
		'{"manifest_version":null}',
		'{"manifest_version":true}',
		'{"manifest_version":3.0}',
		'{"manifest_version":[]}',
		'{"manifest_version":{}}',
	],
	ids=[
		'missing-file',
		'invalid-json',
		'not-an-object',
		'missing-version',
		'string-version',
		'null-version',
		'bool-version',
		'float-version',
		'list-version',
		'object-version',
	],
)
def test_crx_fallback_invalid_manifest_is_redownloaded_on_next_launch(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crx_version: int, manifest_contents: str | None
) -> None:
	import io
	import zipfile

	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	header = b'Cr24' + crx_version.to_bytes(4, 'little') + (b'\x00' * (8 if crx_version == 2 else 4))
	crx_payloads: list[bytes] = []
	for contents in [manifest_contents, json.dumps({'manifest_version': 3, 'name': 'recovered', 'version': '1'})]:
		buffer = io.BytesIO()
		with zipfile.ZipFile(buffer, 'w') as archive:
			if contents is None:
				archive.writestr('background.js', 'missing manifest')
			else:
				archive.writestr('manifest.json', contents)
		crx_payloads.append(header + buffer.getvalue())
	cached_crx.write_bytes(crx_payloads[0])

	real_zip_file = zipfile.ZipFile

	def force_crx_fallback(file: str | Path, mode: Literal['r'] = 'r'):
		if str(file).endswith('.crx'):
			raise zipfile.BadZipFile('force CRX header fallback')
		return real_zip_file(file, mode)

	monkeypatch.setattr(zipfile, 'ZipFile', force_crx_fallback)
	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()
	extension_dir = cache_dir / EXTENSION_IDS[0]
	assert not cached_crx.exists()
	assert not extension_dir.exists()

	download_calls: list[Path] = []

	def write_valid_crx(self: BrowserProfile, url: str, output_path: Path) -> None:
		download_calls.append(output_path)
		output_path.write_bytes(crx_payloads[1])

	monkeypatch.setattr(BrowserProfile, '_download_extension', write_valid_crx)
	paths = profile._ensure_default_extensions_downloaded()

	assert download_calls == [cached_crx]
	assert str(extension_dir) in paths
	assert json.loads((extension_dir / 'manifest.json').read_text(encoding='utf-8'))['name'] == 'recovered'
	assert not (cache_dir / f'.{EXTENSION_IDS[0]}.extracting').exists()


def test_valid_manifest_v2_cache_is_preserved_when_extension_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	import zipfile

	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	cache_dir.mkdir(parents=True, exist_ok=True)
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	with zipfile.ZipFile(cached_crx, 'w') as archive:
		archive.writestr('manifest.json', json.dumps({'manifest_version': 2, 'name': 'legacy', 'version': '1'}))
	for extension_id in EXTENSION_IDS[1:]:
		_create_valid_extracted_extension(cache_dir, extension_id)

	download_calls: list[Path] = []

	def unexpected_download(self: BrowserProfile, url: str, output_path: Path) -> None:
		download_calls.append(output_path)

	monkeypatch.setattr(BrowserProfile, '_download_extension', unexpected_download)
	paths = BrowserProfile(enable_default_extensions=True)._ensure_default_extensions_downloaded()

	assert download_calls == []
	assert cached_crx.exists()
	assert (cache_dir / EXTENSION_IDS[0] / 'manifest.json').is_file()
	assert str(cache_dir / EXTENSION_IDS[0]) not in paths


@pytest.mark.parametrize(
	'manifest_contents',
	[
		'{invalid-json',
		'[]',
		'{}',
		'{"manifest_version":"3"}',
		'{"manifest_version":null}',
		'{"manifest_version":true}',
		'{"manifest_version":3.0}',
		'{"manifest_version":[]}',
		'{"manifest_version":{}}',
	],
	ids=[
		'invalid-json',
		'not-an-object',
		'missing-version',
		'string-version',
		'null-version',
		'bool-version',
		'float-version',
		'list-version',
		'object-version',
	],
)
@pytest.mark.parametrize('valid_cached_archive', [True, False], ids=['reextract', 'redownload'])
def test_invalid_extracted_manifest_recovers_existing_cache(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest_contents: str, valid_cached_archive: bool
) -> None:
	import io
	import zipfile

	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	for extension_id in EXTENSION_IDS:
		_create_valid_extracted_extension(cache_dir, extension_id)
	extension_dir = cache_dir / EXTENSION_IDS[0]
	manifest_path = extension_dir / 'manifest.json'
	manifest_path.write_text(manifest_contents, encoding='utf-8')
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	valid_manifest = json.dumps({'manifest_version': 3, 'name': 'recovered', 'version': '1'})
	archives: list[bytes] = []
	for contents in [valid_manifest if valid_cached_archive else manifest_contents, valid_manifest]:
		buffer = io.BytesIO()
		with zipfile.ZipFile(buffer, 'w') as archive:
			archive.writestr('manifest.json', contents)
		archives.append(buffer.getvalue())
	cached_crx.write_bytes(archives[0])
	download_calls: list[Path] = []

	def write_valid_archive(self: BrowserProfile, url: str, output_path: Path) -> None:
		download_calls.append(output_path)
		output_path.write_bytes(archives[1])

	monkeypatch.setattr(BrowserProfile, '_download_extension', write_valid_archive)
	profile = BrowserProfile(enable_default_extensions=True)
	paths = profile._ensure_default_extensions_downloaded()
	assert download_calls == []
	if valid_cached_archive:
		assert str(extension_dir) in paths
		assert cached_crx.exists()
	else:
		assert not cached_crx.exists()
		assert not extension_dir.exists()
		paths = profile._ensure_default_extensions_downloaded()
		assert download_calls == [cached_crx]
		assert str(extension_dir) in paths
	assert json.loads(manifest_path.read_text(encoding='utf-8'))['name'] == 'recovered'


@pytest.mark.parametrize('failure_point', ['stat', 'read'])
def test_manifest_ioerror_preserves_completed_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	cache_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	for extension_id in EXTENSION_IDS:
		_create_valid_extracted_extension(cache_dir, extension_id)
	manifest_path = cache_dir / EXTENSION_IDS[0] / 'manifest.json'
	cached_crx = cache_dir / f'{EXTENSION_IDS[0]}.crx'
	cached_crx.write_bytes(b'preserved cache')
	real_json_load = json.load
	real_stat = os.stat
	stat_failures = 0

	def fail_target_stat(path, *args, **kwargs):
		nonlocal stat_failures
		if path == manifest_path or path == str(manifest_path):
			stat_failures += 1
			raise PermissionError('simulated manifest stat failure')
		return real_stat(path, *args, **kwargs)

	def fail_target_manifest(file, *args, **kwargs):
		if file.name == str(manifest_path):
			raise PermissionError('simulated manifest read failure')
		return real_json_load(file, *args, **kwargs)

	extract_calls: list[Path] = []

	def unexpected_extract(self: BrowserProfile, crx_path: Path, extract_dir: Path) -> None:
		extract_calls.append(crx_path)

	if failure_point == 'stat':
		monkeypatch.setattr(os, 'stat', fail_target_stat)
	else:
		monkeypatch.setattr(json, 'load', fail_target_manifest)
	monkeypatch.setattr(BrowserProfile, '_extract_extension', unexpected_extract)
	profile = BrowserProfile(enable_default_extensions=True)
	profile._ensure_default_extensions_downloaded()

	if failure_point == 'stat':
		assert stat_failures > 0
	assert extract_calls == []
	assert cached_crx.read_bytes() == b'preserved cache'
	monkeypatch.setattr(os, 'stat', real_stat)
	assert manifest_path.is_file()
	monkeypatch.setattr(json, 'load', real_json_load)
	paths = profile._ensure_default_extensions_downloaded()
	assert str(manifest_path.parent) in paths
	assert extract_calls == []
	assert cached_crx.read_bytes() == b'preserved cache'
