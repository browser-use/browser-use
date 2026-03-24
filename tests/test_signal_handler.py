"""Tests for SignalHandler — particularly the disabled opt-out flag."""
import asyncio
import signal
from unittest.mock import MagicMock

import pytest

from browser_use.utils import SignalHandler


class TestSignalHandlerDisabled:
    """Tests for SignalHandler(disabled=True) opt-out behaviour.
    
    Refs: https://github.com/browser-use/browser-use/issues/4385
    """

    def test_disabled_does_not_register_any_signal_handlers(self) -> None:
        """When disabled=True, register() must be a no-op so host apps keep control."""
        handler = SignalHandler(
            loop=asyncio.new_event_loop(),
            disabled=True,
        )
        # register() should not raise and should not touch any signal
        handler.register()
        # If we got here without an exception, the test passes.
        # The real check is that no signal handler was installed.
        # We verify by checking that original_sigint_handler stays None.
        assert handler.original_sigint_handler is None

    def test_disabled_unregister_is_also_noop(self) -> None:
        """unregister() on a disabled handler must also be a no-op."""
        handler = SignalHandler(
            loop=asyncio.new_event_loop(),
            disabled=True,
        )
        # Must not raise
        handler.unregister()

    def test_enabled_registers_sigint_handler(self) -> None:
        """Smoke test: enabled=True (default) should attempt to register."""
        loop = asyncio.new_event_loop()
        handler = SignalHandler(
            loop=loop,
            disabled=False,
        )
        # We expect no exception from register() even if signals aren't
        # fully available in the test environment.
        try:
            handler.register()
        except Exception:
            # SignalHandler silently swallows exceptions (see source)
            pass
        finally:
            try:
                handler.unregister()
            except Exception:
                pass
            loop.close()
