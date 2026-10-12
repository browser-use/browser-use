import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog


def _make_watchdog() -> tuple[StorageStateWatchdog, MagicMock]:
	browser_session = MagicMock()
	browser_session.cdp_client = object()
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
