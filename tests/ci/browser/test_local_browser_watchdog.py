import asyncio

import pytest

from browser_use.browser.views import BrowserError
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


@pytest.mark.asyncio
async def test_create_subprocess_exec_reports_unsupported_event_loop(monkeypatch):
	async def unsupported_subprocess_exec(*_cmd, **_kwargs):
		raise NotImplementedError

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', unsupported_subprocess_exec)

	with pytest.raises(BrowserError) as exc_info:
		await LocalBrowserWatchdog._create_subprocess_exec('chrome', '--remote-debugging-port=9222')

	assert isinstance(exc_info.value.__cause__, NotImplementedError)
	message = str(exc_info.value)
	assert 'does not support subprocesses' in message
	assert 'WindowsProactorEventLoopPolicy' in message
	assert 'Uvicorn/FastAPI' in message
