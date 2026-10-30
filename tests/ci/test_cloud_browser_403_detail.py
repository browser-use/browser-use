"""create_browser must surface the server's 403 detail instead of a subscription message."""

from __future__ import annotations

import pytest

from browser_use.browser.cloud.cloud import CloudBrowserClient
from browser_use.browser.cloud.views import CloudBrowserAuthError, CreateBrowserRequest


class _Resp:
	def __init__(self, status_code: int, payload: dict | None = None):
		self.status_code = status_code
		self._payload = payload or {}
		self.is_success = 200 <= status_code < 300

	def json(self):
		return self._payload


@pytest.mark.asyncio
async def test_403_includes_server_detail(monkeypatch):
	client = CloudBrowserClient()

	async def fake_request(method, path, *, headers, json):
		return _Resp(403, {'detail': 'cloud_timeout exceeded for free tier'}), 'v2'

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-key')
	monkeypatch.setattr(client, '_request_browser_api', fake_request)

	with pytest.raises(CloudBrowserAuthError, match='cloud_timeout exceeded for free tier') as exc:
		await client.create_browser(CreateBrowserRequest())
	assert 'subscription' not in str(exc.value).lower()


@pytest.mark.asyncio
async def test_403_without_detail_avoids_subscription_wording(monkeypatch):
	client = CloudBrowserClient()

	async def fake_request(method, path, *, headers, json):
		return _Resp(403, {}), 'v2'

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-key')
	monkeypatch.setattr(client, '_request_browser_api', fake_request)

	with pytest.raises(CloudBrowserAuthError) as exc:
		await client.create_browser(CreateBrowserRequest())
	msg = str(exc.value).lower()
	assert 'subscription' not in msg
	assert '403' in msg or 'forbidden' in msg
