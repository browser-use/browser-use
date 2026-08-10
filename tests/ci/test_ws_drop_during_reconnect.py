"""Tests for WebSocket drop detection during the reconnect window.

Verifies fix for issue #5366: when a CDP WebSocket drops while
_auto_reconnect() is in progress (_reconnecting=True), the one-shot
done_callback must not silently discard the event.  Instead it sets
_drop_during_reconnect so the finally block can re-schedule.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.session import BrowserSession


@pytest.fixture
def session() -> BrowserSession:
    """Create a minimal BrowserSession for unit testing."""
    s = BrowserSession(cdp_url='ws://localhost:9222/devtools/browser/fake')
    s._intentional_stop = False
    return s


class TestDropDuringReconnectFlag:
    """The done_callback sets _drop_during_reconnect when _reconnecting is True."""

    async def test_flag_set_when_drop_during_reconnect(self, session: BrowserSession) -> None:
        """When the callback fires while _reconnecting=True, the flag must be set."""
        session._reconnecting = True
        session._drop_during_reconnect = False

        # Build a mock CDPClient with a live Future as its _message_handler_task
        mock_task = asyncio.get_running_loop().create_future()
        mock_cdp = MagicMock()
        mock_cdp._message_handler_task = mock_task
        session._cdp_client_root = mock_cdp

        session._attach_ws_drop_callback()

        # Complete the task to simulate a WS drop — the callback should fire
        mock_task.set_result(None)
        await asyncio.sleep(0)

        assert session._drop_during_reconnect is True, (
            '_drop_during_reconnect should be True after a drop while _reconnecting=True'
        )

    async def test_flag_not_set_when_intentional_stop(self, session: BrowserSession) -> None:
        """When _intentional_stop is True, the callback should not set the flag."""
        session._reconnecting = True
        session._intentional_stop = True
        session._drop_during_reconnect = False

        mock_task = asyncio.get_running_loop().create_future()
        mock_cdp = MagicMock()
        mock_cdp._message_handler_task = mock_task
        session._cdp_client_root = mock_cdp

        session._attach_ws_drop_callback()
        mock_task.set_result(None)
        await asyncio.sleep(0)

        assert session._drop_during_reconnect is False, (
            '_drop_during_reconnect should remain False when _intentional_stop is True'
        )

    async def test_flag_not_set_when_no_cdp_url(self, session: BrowserSession) -> None:
        """When cdp_url is empty, the callback should not set the flag."""
        session._reconnecting = True
        session.browser_profile.cdp_url = None
        session._drop_during_reconnect = False

        mock_task = asyncio.get_running_loop().create_future()
        mock_cdp = MagicMock()
        mock_cdp._message_handler_task = mock_task
        session._cdp_client_root = mock_cdp

        session._attach_ws_drop_callback()
        mock_task.set_result(None)
        await asyncio.sleep(0)

        assert session._drop_during_reconnect is False, (
            '_drop_during_reconnect should remain False when cdp_url is None'
        )


class TestAutoReconnectReschedule:
    """The finally block in _auto_reconnect detects the flag and re-schedules."""

    async def test_reschedule_on_flag(self, session: BrowserSession) -> None:
        """If _drop_during_reconnect is set during reconnect, a new reconnect is scheduled."""
        reconnect_call_count = 0

        async def mock_reconnect(self_inner):
            nonlocal reconnect_call_count
            reconnect_call_count += 1
            # On the first call, simulate a WS drop arriving mid-reconnect
            if reconnect_call_count == 1:
                session._drop_during_reconnect = True

        with patch.object(BrowserSession, 'reconnect', mock_reconnect):
            with patch.object(BrowserSession, '_setup_proxy_auth', AsyncMock()):
                with patch.object(BrowserSession, '_attach_ws_drop_callback', lambda self_inner: None):
                    # Run _auto_reconnect — the first call should succeed, detect the
                    # flag, and schedule a second call.
                    await session._auto_reconnect(max_attempts=1)
                    # Let the re-scheduled task run
                    await asyncio.sleep(0.1)

        assert reconnect_call_count >= 2, (
            f'Expected reconnect to be called at least twice (re-scheduled), '
            f'but was called {reconnect_call_count} time(s)'
        )
        assert session._drop_during_reconnect is False, (
            '_drop_during_reconnect should be cleared after re-schedule'
        )

    async def test_no_reschedule_without_flag(self, session: BrowserSession) -> None:
        """If _drop_during_reconnect is NOT set, no extra reconnect is scheduled."""
        reconnect_call_count = 0

        async def mock_reconnect(self_inner):
            nonlocal reconnect_call_count
            reconnect_call_count += 1

        with patch.object(BrowserSession, 'reconnect', mock_reconnect):
            with patch.object(BrowserSession, '_setup_proxy_auth', AsyncMock()):
                with patch.object(BrowserSession, '_attach_ws_drop_callback', lambda self_inner: None):
                    await session._auto_reconnect(max_attempts=1)
                    await asyncio.sleep(0.1)

        assert reconnect_call_count == 1, (
            f'Expected reconnect to be called exactly once, '
            f'but was called {reconnect_call_count} time(s)'
        )

    async def test_flag_reset_at_start(self, session: BrowserSession) -> None:
        """_drop_during_reconnect is reset to False at the start of _auto_reconnect."""
        session._drop_during_reconnect = True

        async def mock_reconnect(self_inner):
            # Verify the flag was cleared before reconnect() runs
            assert session._drop_during_reconnect is False, (
                '_drop_during_reconnect should be reset at the start of _auto_reconnect'
            )

        with patch.object(BrowserSession, 'reconnect', mock_reconnect):
            with patch.object(BrowserSession, '_setup_proxy_auth', AsyncMock()):
                with patch.object(BrowserSession, '_attach_ws_drop_callback', lambda self_inner: None):
                    await session._auto_reconnect(max_attempts=1)
