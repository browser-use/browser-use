import pytest

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from unittest.mock import AsyncMock, MagicMock

class TestBrowserContext:
    @pytest.mark.asyncio
    async def test_browser_context_initialization(self):
        """
        Test the initialization of BrowserContext with custom configuration.
        """
        # Mock the Browser object
        mock_browser = MagicMock()
        mock_browser.get_playwright_browser = AsyncMock()

        # Create a custom configuration
        config = BrowserContextConfig(
            cookies_file="test_cookies.json",
            minimum_wait_page_load_time=1.0,
            browser_window_size={'width': 1024, 'height': 768},
            highlight_elements=False
        )

        # Initialize BrowserContext
        context = BrowserContext(mock_browser, config)

        # Assert that the context is initialized correctly
        assert context.context_id is not None
        assert context.config == config
        assert context.browser == mock_browser
        assert context.session is None

        # Test the __aenter__ method
        async with context as ctx:
            assert ctx == context
            assert ctx.session is not None

        # Assert that the close method was called
        mock_browser.get_playwright_browser.assert_called_once()