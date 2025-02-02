import asyncio
import pytest

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from playwright.async_api import Browser as PlaywrightBrowser, BrowserContext as PlaywrightBrowserContext
from unittest.mock import AsyncMock, MagicMock, patch

class TestBrowserContext:
    @pytest.mark.asyncio
    async def test_browser_context_initialization(self):
        """
        Test the initialization of BrowserContext with a custom configuration.
        This test verifies that:
        1. The BrowserContext is created with the given configuration.
        2. The _initialize_session method is called during initialization.
        3. The context_id is set and is a valid UUID.
        """
        # Mock the Browser class
        mock_browser = MagicMock()
        mock_browser.get_playwright_browser.return_value = AsyncMock(spec=PlaywrightBrowser)

        # Create a custom configuration
        config = BrowserContextConfig(
            cookies_file="test_cookies.json",
            browser_window_size={'width': 1024, 'height': 768},
            user_agent="Test User Agent"
        )

        # Patch the _initialize_session method
        with patch.object(BrowserContext, '_initialize_session', new_callable=AsyncMock) as mock_init_session:
            # Create the BrowserContext instance
            browser_context = BrowserContext(mock_browser, config)

            # Initialize the session
            await browser_context.__aenter__()

            # Assert that _initialize_session was called
            mock_init_session.assert_called_once()

            # Check if the context_id is set and is a valid UUID
            assert browser_context.context_id is not None
            assert len(browser_context.context_id) == 36  # UUID length

            # Verify that the configuration was set correctly
            assert browser_context.config == config
            assert browser_context.config.cookies_file == "test_cookies.json"
            assert browser_context.config.browser_window_size == {'width': 1024, 'height': 768}
            assert browser_context.config.user_agent == "Test User Agent"

        # Cleanup
        await browser_context.__aexit__(None, None, None)