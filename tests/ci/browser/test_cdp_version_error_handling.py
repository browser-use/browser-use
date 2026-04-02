"""
Test that CDP /json/version endpoint errors produce clear error messages
instead of cryptic JSONDecodeError or KeyError.

This tests the fix for: When connecting to a remote browser via HTTP CDP URL,
if the /json/version endpoint returns a non-200 status, non-JSON body, or
a JSON response missing 'webSocketDebuggerUrl', the user should get a clear
RuntimeError instead of an unhelpful low-level exception.

Reproduces the scenario from issue #4050 where users connecting through
proxies or to misconfigured remote browsers got JSONDecodeError.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


def _make_mock_response(status_code: int, text: str, json_data: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response with the given status, text, and optional JSON."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = Exception(f'Expecting value: line 1 column 1 (char 0)')
    return resp


@pytest.mark.asyncio
async def test_cdp_version_non_200_raises_clear_error():
    """HTTP 502 from /json/version should raise RuntimeError with status code, not JSONDecodeError."""
    session = BrowserSession(cdp_url='http://remote-browser:9222')

    mock_response = _make_mock_response(
        status_code=502,
        text='<html><body>Bad Gateway</body></html>',
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('browser_use.browser.session.httpx.AsyncClient', return_value=mock_client):
        with pytest.raises(RuntimeError, match=r'HTTP 502'):
            await session.connect()


@pytest.mark.asyncio
async def test_cdp_version_non_json_raises_clear_error():
    """Non-JSON response body should raise RuntimeError mentioning 'not valid JSON'."""
    session = BrowserSession(cdp_url='http://remote-browser:9222')

    mock_response = _make_mock_response(
        status_code=200,
        text='This is not JSON',
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('browser_use.browser.session.httpx.AsyncClient', return_value=mock_client):
        with pytest.raises(RuntimeError, match=r'not valid JSON'):
            await session.connect()


@pytest.mark.asyncio
async def test_cdp_version_missing_ws_url_raises_clear_error():
    """JSON response without 'webSocketDebuggerUrl' should raise RuntimeError with available keys."""
    session = BrowserSession(cdp_url='http://remote-browser:9222')

    mock_response = _make_mock_response(
        status_code=200,
        text='{"Browser": "Chrome/120"}',
        json_data={'Browser': 'Chrome/120'},
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('browser_use.browser.session.httpx.AsyncClient', return_value=mock_client):
        with pytest.raises(RuntimeError, match=r'missing "webSocketDebuggerUrl"'):
            await session.connect()


@pytest.mark.asyncio
async def test_cdp_version_success_sets_ws_url():
    """Valid /json/version response should set cdp_url to the WebSocket URL."""
    ws_url = 'ws://remote-browser:9222/devtools/browser/abc123'
    session = BrowserSession(cdp_url='http://remote-browser:9222')

    mock_response = _make_mock_response(
        status_code=200,
        text=f'{{"webSocketDebuggerUrl": "{ws_url}", "Browser": "Chrome/120"}}',
        json_data={'webSocketDebuggerUrl': ws_url, 'Browser': 'Chrome/120'},
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('browser_use.browser.session.httpx.AsyncClient', return_value=mock_client):
        with patch('browser_use.browser.session.CDPClient') as mock_cdp_class:
            mock_cdp = AsyncMock()
            mock_cdp_class.return_value = mock_cdp
            mock_cdp.start = AsyncMock()
            mock_cdp.stop = AsyncMock()
            mock_cdp.send = MagicMock()
            mock_cdp.send.Target = MagicMock()
            mock_cdp.send.Target.setAutoAttach = AsyncMock()
            mock_cdp.send.Target.getTargets = AsyncMock(return_value={'targetInfos': []})
            mock_cdp.send.Target.createTarget = AsyncMock(return_value={'targetId': 'test-id'})

            with patch('browser_use.browser.session_manager.SessionManager') as mock_sm_class:
                mock_sm = AsyncMock()
                mock_sm_class.return_value = mock_sm

                try:
                    await session.connect()
                except Exception:
                    pass  # connect() may fail on later steps, that's fine

                # The key assertion: cdp_url should be set to the WebSocket URL
                assert session.browser_profile.cdp_url == ws_url
