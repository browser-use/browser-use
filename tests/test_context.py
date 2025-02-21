import asyncio
import pytest
from browser_use.browser.context import (
    BrowserContext,
    BrowserContextConfig,
    BrowserError,
)
from unittest.mock import (
    AsyncMock,
    MagicMock,
)


@pytest.mark.asyncio
async def test_navigate_to_non_allowed_url():
    """
    Tests that navigating to a non-allowed URL in BrowserContext
    raises BrowserError. This test creates a dummy Browser object with
    allowed_domains set to only permit 'example.com'. It then successfully
    navigates to an allowed URL and subsequently attempts navigating to a disallowed URL,
    expecting a BrowserError.
    """
    dummy_browser = MagicMock()
    dummy_browser.config = MagicMock()
    dummy_browser.config.cdp_url = None
    dummy_browser.config.chrome_instance_path = None
    fake_playwright_browser = AsyncMock()
    fake_playwright_browser.contexts = []
    dummy_browser.get_playwright_browser = AsyncMock(
        return_value=fake_playwright_browser
    )
    fake_playwright_browser.new_context = AsyncMock()
    fake_context = AsyncMock()
    fake_playwright_browser.new_context.return_value = fake_context
    fake_page = AsyncMock()
    fake_page.url = "http://example.com/home"
    fake_page.wait_for_load_state = AsyncMock()
    fake_page.goto = AsyncMock()
    fake_page.reload = AsyncMock()
    fake_page.title = AsyncMock(return_value="Fake Title")
    fake_context.new_page = AsyncMock(return_value=fake_page)
    config = BrowserContextConfig(allowed_domains=["example.com"])
    ctx = BrowserContext(dummy_browser, config=config)
    await ctx._initialize_session()
    await ctx.navigate_to("http://example.com/path")
    fake_page.goto.assert_called_with("http://example.com/path")
    with pytest.raises(BrowserError) as exc_info:
        await ctx.navigate_to("http://malicious.com")
    assert "non-allowed" in str(exc_info.value)
