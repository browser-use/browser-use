from __future__ import annotations

import asyncio

import aiohttp

from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


def test_wait_for_cdp_url_bypasses_env_proxy_for_localhost(monkeypatch):
	"""Local CDP readiness polling must not route 127.0.0.1 through env proxies."""
	client_session_kwargs = []
	requested_urls = []

	class FakeResponse:
		status = 200

		async def __aenter__(self):
			return self

		async def __aexit__(self, exc_type, exc, tb):
			return None

	class FakeClientSession:
		def __init__(self, **kwargs):
			client_session_kwargs.append(kwargs)

		async def __aenter__(self):
			return self

		async def __aexit__(self, exc_type, exc, tb):
			return None

		def get(self, url):
			requested_urls.append(url)
			return FakeResponse()

	monkeypatch.setattr(aiohttp, 'ClientSession', FakeClientSession)

	cdp_url = asyncio.run(LocalBrowserWatchdog._wait_for_cdp_url(9222, timeout=0.1))

	assert cdp_url == 'http://127.0.0.1:9222/'
	assert requested_urls == ['http://127.0.0.1:9222/json/version']
	assert client_session_kwargs == [{'trust_env': False}]
