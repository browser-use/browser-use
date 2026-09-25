import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from websockets.protocol import State

from browser_use.browser.session import BrowserSession
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


def _make_unconnected_watchdog() -> tuple[StorageStateWatchdog, BrowserSession]:
	browser_session = BrowserSession(headless=True)
	watchdog = StorageStateWatchdog.model_construct(
		event_bus=browser_session.event_bus, browser_session=browser_session, auto_save_interval=0.01
	)
	return watchdog, browser_session


async def test_cookie_checks_without_a_cdp_client_do_not_raise():
	watchdog, _ = _make_unconnected_watchdog()

	assert await watchdog._have_cookies_changed() is False
	assert await watchdog.get_current_cookies() == []
	await watchdog.add_cookies([])


async def test_monitoring_loop_logs_no_error_once_the_cdp_client_is_gone(
	caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
	watchdog, browser_session = _make_unconnected_watchdog()
	get_cookies = AsyncMock(return_value=[])
	monkeypatch.setattr(BrowserSession, '_cdp_get_cookies', get_cookies)
	browser_session._cdp_client_root = MagicMock()
	browser_session._cdp_client_root.ws.state = State.OPEN
	assert browser_session.is_cdp_connected
	await watchdog._start_monitoring()

	browser_use_logger = logging.getLogger('browser_use')
	browser_use_logger.addHandler(caplog.handler)
	try:
		async with asyncio.timeout(1):
			while not get_cookies.await_count:
				await asyncio.sleep(0.01)
		browser_session._cdp_client_root = None
		await asyncio.sleep(0.1)
	finally:
		browser_use_logger.removeHandler(caplog.handler)
		await watchdog._stop_monitoring()

	assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []


async def test_reset_stops_the_storage_state_monitoring_loop():
	watchdog, browser_session = _make_unconnected_watchdog()
	browser_session._cdp_client_root = AsyncMock()
	browser_session._storage_state_watchdog = watchdog
	await watchdog._start_monitoring()

	await browser_session.reset()

	assert watchdog._monitoring_task is not None
	assert watchdog._monitoring_task.done()
