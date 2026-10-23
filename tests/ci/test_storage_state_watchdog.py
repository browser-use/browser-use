import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog


def _make_watchdog() -> tuple[StorageStateWatchdog, MagicMock]:
	browser_session = MagicMock()
	browser_session.is_cdp_connected = True
	browser_session.get_or_create_cdp_session = AsyncMock(return_value=object())
	browser_session._cdp_get_storage_state = AsyncMock(return_value={'cookies': [], 'origins': []})
	browser_session._cdp_set_cookies = AsyncMock()
	browser_session._cdp_add_init_script = AsyncMock()

	watchdog = StorageStateWatchdog.model_construct(event_bus=MagicMock(), browser_session=browser_session)
	return watchdog, browser_session


async def test_load_storage_state_reads_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	unicode_value = 'zażółć gęślą jaźń'
	storage_path = tmp_path / 'storage-state.json'
	storage_path.write_text(
		json.dumps(
			{
				'cookies': [],
				'origins': [
					{
						'origin': 'https://example.com',
						'localStorage': [{'name': 'greeting', 'value': unicode_value}],
					}
				],
			},
			ensure_ascii=False,
		),
		encoding='utf-8',
	)

	encodings: list[str | None] = []
	original_read_text = anyio.Path.read_text

	async def track_encoding(path: anyio.Path, encoding: str | None = None, errors: str | None = None) -> str:
		encodings.append(encoding)
		return await original_read_text(path, encoding=encoding, errors=errors)

	monkeypatch.setattr(anyio.Path, 'read_text', track_encoding)
	watchdog, browser_session = _make_watchdog()

	await watchdog._load_storage_state(str(storage_path))

	assert encodings == ['utf-8']
	browser_session._cdp_add_init_script.assert_awaited_once()
	assert json.dumps(unicode_value) in browser_session._cdp_add_init_script.await_args.args[0]


async def test_save_storage_state_reads_existing_file_as_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	unicode_value = '你好，世界'
	storage_path = tmp_path / 'storage-state.json'
	storage_path.write_text(
		json.dumps(
			{
				'cookies': [
					{
						'name': 'greeting',
						'value': unicode_value,
						'domain': 'example.com',
						'path': '/',
					}
				],
				'origins': [],
			},
			ensure_ascii=False,
		),
		encoding='utf-8',
	)

	encodings: list[str | None] = []
	original_read_text = Path.read_text

	def track_encoding(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
		if path == storage_path.resolve():
			encodings.append(encoding)
		return original_read_text(path, encoding=encoding, errors=errors)

	monkeypatch.setattr(Path, 'read_text', track_encoding)
	watchdog, browser_session = _make_watchdog()
	browser_session._cdp_get_storage_state.return_value = {
		'cookies': [
			{
				'name': 'current',
				'value': 'new-value',
				'domain': 'example.com',
				'path': '/',
			}
		],
		'origins': [],
	}

	await watchdog._save_storage_state(str(storage_path))

	assert encodings == ['utf-8']
	saved_state = json.loads(original_read_text(storage_path, encoding='utf-8'))
	saved_cookies = {cookie['name']: cookie['value'] for cookie in saved_state['cookies']}
	assert saved_cookies == {'greeting': unicode_value, 'current': 'new-value'}


async def test_save_storage_state_skips_when_no_cdp_client(tmp_path: Path):
	"""Regression test for #6005: stop()/kill() dispatch SaveStorageStateEvent even when the
	root CDP client was never initialized; the save must return quietly instead of raising
	"AssertionError: Root CDP client not initialized"."""
	watchdog, browser_session = _make_watchdog()
	# cubic P1 (PR #6019): the guard must use is_cdp_connected, since the cdp_client
	# property itself asserts when the root CDP client is unset — i.e. on a REAL
	# session `cdp_client is None` can never be evaluated. Configure the mock so
	# is_cdp_connected returns False (no browser connection) and the property path
	# would still raise if the guard were ever switched back to it.
	browser_session.cdp_client = property(lambda self: (_ for _ in ()).throw(AssertionError('Root CDP client not initialized')))
	browser_session.is_cdp_connected = False
	browser_session.browser_profile.storage_state = str(tmp_path / 'storage-state.json')
	browser_session.get_or_create_cdp_session = AsyncMock(side_effect=AssertionError('Root CDP client not initialized'))

	# Must not raise
	await watchdog._save_storage_state()

	browser_session.get_or_create_cdp_session.assert_not_awaited()


async def test_save_storage_state_skips_when_no_save_path():
	"""Regression test for #6005: the save-path check must run before any CDP session
	creation, so a save with no configured storage state never touches CDP."""
	watchdog, browser_session = _make_watchdog()
	browser_session.cdp_client = property(lambda self: (_ for _ in ()).throw(AssertionError('Root CDP client not initialized')))
	browser_session.is_cdp_connected = False
	browser_session.browser_profile.storage_state = None
	browser_session.get_or_create_cdp_session = AsyncMock(side_effect=AssertionError('Root CDP client not initialized'))

	# Must not raise even though no CDP client exists and no path is configured
	await watchdog._save_storage_state()

	browser_session.get_or_create_cdp_session.assert_not_awaited()
