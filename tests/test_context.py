import json
import pytest

from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

@pytest.fixture
def mock_browser():
    mock = MagicMock(spec=Browser)
    mock.get_playwright_browser = AsyncMock()
    mock.config = MagicMock()
    mock.config.cdp_url = None
    mock.config.chrome_instance_path = None
    return mock

class TestBrowserContext:
    @pytest.mark.asyncio
    async def test_browser_context_initialization_with_custom_config(self, mock_browser):
        """
        Test that BrowserContext is properly initialized with a custom BrowserContextConfig.
        This test checks if the custom configuration is correctly applied to the BrowserContext instance.
        """
        # Create a custom BrowserContextConfig
        custom_config = BrowserContextConfig(
            cookies_file="custom_cookies.json",
            minimum_wait_page_load_time=1.0,
            maximum_wait_page_load_time=10.0,
            browser_window_size={'width': 1920, 'height': 1080},
            user_agent="Custom User Agent",
            highlight_elements=False
        )

        # Mock the PlaywrightBrowser and PlaywrightBrowserContext
        mock_playwright_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_playwright_browser.new_context.return_value = mock_context
        mock_browser.get_playwright_browser.return_value = mock_playwright_browser

        # Initialize BrowserContext with the custom config
        browser_context = BrowserContext(mock_browser, config=custom_config)

        # Use context manager to initialize the session
        async with browser_context:
            # Check if the custom config was applied
            assert browser_context.config == custom_config

            # Verify that the browser methods were called with the correct parameters
            mock_playwright_browser.new_context.assert_called_once_with(
                viewport=custom_config.browser_window_size,
                no_viewport=False,
                user_agent=custom_config.user_agent,
                java_script_enabled=True,
                bypass_csp=custom_config.disable_security,
                ignore_https_errors=custom_config.disable_security,
                record_video_dir=custom_config.save_recording_path,
                locale=custom_config.locale,
            )

            # Verify that the context was created
            assert browser_context.session is not None
            assert browser_context.session.context == mock_context

        # Verify that the context was closed after exiting the context manager
        mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_context_initialization_with_custom_config(self, mock_browser):
        """
        Test that BrowserContext is properly initialized with a custom BrowserContextConfig.
        This test checks if the custom configuration is correctly applied to the BrowserContext instance
        and verifies that the browser methods are called with the correct parameters.
        It also mocks the cookie file loading to avoid file system dependencies.
        """
        # Create a custom BrowserContextConfig
        custom_config = BrowserContextConfig(
            cookies_file="custom_cookies.json",
            minimum_wait_page_load_time=1.0,
            maximum_wait_page_load_time=10.0,
            browser_window_size={'width': 1920, 'height': 1080},
            user_agent="Custom User Agent",
            highlight_elements=False
        )

        # Mock the PlaywrightBrowser and PlaywrightBrowserContext
        mock_playwright_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_playwright_browser.new_context.return_value = mock_context
        mock_browser.get_playwright_browser.return_value = mock_playwright_browser

        # Mock the cookie file loading
        mock_cookies = [{"name": "test_cookie", "value": "test_value"}]
        mock_file = mock_open(read_data=json.dumps(mock_cookies))

        # Initialize BrowserContext with the custom config
        with patch('builtins.open', mock_file):
            browser_context = BrowserContext(mock_browser, config=custom_config)

            # Use context manager to initialize the session
            async with browser_context:
                # Check if the custom config was applied
                assert browser_context.config == custom_config

                # Verify that the browser methods were called with the correct parameters
                mock_playwright_browser.new_context.assert_called_once_with(
                    viewport=custom_config.browser_window_size,
                    no_viewport=False,
                    user_agent=custom_config.user_agent,
                    java_script_enabled=True,
                    bypass_csp=custom_config.disable_security,
                    ignore_https_errors=custom_config.disable_security,
                    record_video_dir=custom_config.save_recording_path,
                    locale=custom_config.locale,
                )

                # Verify that the context was created
                assert browser_context.session is not None
                assert browser_context.session.context == mock_context

                # Verify that cookies were loaded
                mock_context.add_cookies.assert_called_once_with(mock_cookies)

            # Verify that the context was closed after exiting the context manager
            mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_context_initialization_with_custom_config(self, mock_browser):
        """
        Test that BrowserContext is properly initialized with a custom BrowserContextConfig.
        This test checks if the custom configuration is correctly applied to the BrowserContext instance,
        verifies that the browser methods are called with the correct parameters, and mocks the cookie file loading.
        """
        # Create a custom BrowserContextConfig
        custom_config = BrowserContextConfig(
            cookies_file="custom_cookies.json",
            minimum_wait_page_load_time=1.0,
            maximum_wait_page_load_time=10.0,
            browser_window_size={'width': 1920, 'height': 1080},
            user_agent="Custom User Agent",
            highlight_elements=False
        )

        # Mock the PlaywrightBrowser and PlaywrightBrowserContext
        mock_playwright_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_playwright_browser.new_context.return_value = mock_context
        mock_browser.get_playwright_browser.return_value = mock_playwright_browser

        # Mock the cookie file content
        mock_cookies = [{"name": "test_cookie", "value": "test_value"}]
        mock_file = mock_open(read_data=json.dumps(mock_cookies))

        # Use patch to mock the file opening operation
        with patch('builtins.open', mock_file):
            # Initialize BrowserContext with the custom config
            browser_context = BrowserContext(mock_browser, config=custom_config)

            # Use context manager to initialize the session
            async with browser_context:
                # Check if the custom config was applied
                assert browser_context.config == custom_config

                # Verify that the browser methods were called with the correct parameters
                mock_playwright_browser.new_context.assert_called_once_with(
                    viewport=custom_config.browser_window_size,
                    no_viewport=False,
                    user_agent=custom_config.user_agent,
                    java_script_enabled=True,
                    bypass_csp=custom_config.disable_security,
                    ignore_https_errors=custom_config.disable_security,
                    record_video_dir=custom_config.save_recording_path,
                    locale=custom_config.locale,
                )

                # Verify that the context was created
                assert browser_context.session is not None
                assert browser_context.session.context == mock_context

                # Verify that cookies were loaded
                mock_context.add_cookies.assert_called_once_with(mock_cookies)

            # Verify that the context was closed after exiting the context manager
            mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_context_initialization_with_custom_config(self, mock_browser):
        """
        Test that BrowserContext is properly initialized with a custom BrowserContextConfig.
        This test checks if the custom configuration is correctly applied to the BrowserContext instance,
        verifies that the browser methods are called with the correct parameters, and mocks the cookie file loading.
        """
        # Create a custom BrowserContextConfig
        custom_config = BrowserContextConfig(
            cookies_file="custom_cookies.json",
            minimum_wait_page_load_time=1.0,
            maximum_wait_page_load_time=10.0,
            browser_window_size={'width': 1920, 'height': 1080},
            user_agent="Custom User Agent",
            highlight_elements=False
        )

        # Mock the PlaywrightBrowser and PlaywrightBrowserContext
        mock_playwright_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_playwright_browser.new_context.return_value = mock_context
        mock_browser.get_playwright_browser.return_value = mock_playwright_browser

        # Mock the cookie file content
        mock_cookies = [{"name": "test_cookie", "value": "test_value"}]
        mock_json_load = MagicMock(return_value=mock_cookies)

        # Use patch to mock the file opening operation and json.load
        with patch('builtins.open', MagicMock()), \
             patch('json.load', mock_json_load):

            # Initialize BrowserContext with the custom config
            browser_context = BrowserContext(mock_browser, config=custom_config)

            # Use context manager to initialize the session
            async with browser_context:
                # Check if the custom config was applied
                assert browser_context.config == custom_config

                # Verify that the browser methods were called with the correct parameters
                mock_playwright_browser.new_context.assert_called_once_with(
                    viewport=custom_config.browser_window_size,
                    no_viewport=False,
                    user_agent=custom_config.user_agent,
                    java_script_enabled=True,
                    bypass_csp=custom_config.disable_security,
                    ignore_https_errors=custom_config.disable_security,
                    record_video_dir=custom_config.save_recording_path,
                    locale=custom_config.locale,
                )

                # Verify that the context was created
                assert browser_context.session is not None
                assert browser_context.session.context == mock_context

                # Verify that cookies were loaded
                mock_context.add_cookies.assert_called_once_with(mock_cookies)

            # Verify that the context was closed after exiting the context manager
            mock_context.close.assert_called_once()