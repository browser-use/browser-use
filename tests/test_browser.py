import asyncio
import pytest
from browser_use.browser.browser import Browser, BrowserConfig

# Define fake implementations to simulate the async_playwright behavior.
class FakeChromium:
    async def connect_over_cdp(self, url, timeout=20000):
        # Assert that the correct URL is passed.
        assert url == "http://dummy-cdp-url"
        # Return a fake browser object.
        return "fake-browser"
class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()
    async def stop(self):
        # Fake cleanup does nothing.
        pass
class FakeAsyncPlaywright:
    async def start(self):
        # Return our fake playwright instance.
        return FakePlaywright()
def fake_async_playwright():
    # This function replaces async_playwright in the Browser module.
    return FakeAsyncPlaywright()
@pytest.mark.asyncio
async def test_get_playwright_browser_via_cdp(monkeypatch):
    """
    Test that Browser.get_playwright_browser properly initializes a browser instance
    when a CDP URL is provided in the configuration.
    This test monkeypatches the async_playwright function to return a fake playwright
    that when used in _setup_cdp returns a fake browser instance. It then verifies that
    the returned browser is the fake one.
    """
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", fake_async_playwright)
    config = BrowserConfig(cdp_url="http://dummy-cdp-url")
    browser_instance = Browser(config=config)
    result = await browser_instance.get_playwright_browser()
    assert result == "fake-browser"
    await browser_instance.close()
class FakeChromiumStandard:
    async def launch(self, headless, args, proxy):
        # Verify that the browser is launched with the default headless value and expected arguments.
        assert headless is False
        assert '--no-sandbox' in args
        # Return a fake browser object.
        return "standard-fake-browser"
class FakePlaywrightStandard:
    def __init__(self):
        self.chromium = FakeChromiumStandard()
    async def stop(self):
        # Fake cleanup does nothing.
        pass
class FakeAsyncPlaywrightStandard:
    async def start(self):
        # Return our fake playwright instance meant for the standard browser launch.
        return FakePlaywrightStandard()
def fake_async_playwright_standard():
    # This function replaces async_playwright in the Browser module for the standard browser branch.
    return FakeAsyncPlaywrightStandard()
@pytest.mark.asyncio
async def test_get_playwright_browser_standard(monkeypatch):
    """
    Test that Browser.get_playwright_browser properly initializes a standard Playwright browser
    instance when no remote connection (cdp_url, wss_url, or chrome_instance_path) is provided.
    This test monkeypatches the async_playwright function to return a fake playwright instance
    that simulates the standard browser launch, then verifies that the returned browser is the fake one.
    """
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", fake_async_playwright_standard)
    config = BrowserConfig()  # Using default configuration (no cdp_url, wss_url or chrome_instance_path)
    browser_instance = Browser(config=config)
    result = await browser_instance.get_playwright_browser()
    assert result == "standard-fake-browser"
    await browser_instance.close()
# Fake classes for simulating a remote browser connection via WSS.
class FakeChromiumWSS:
    async def connect(self, url):
        # Verify that the correct WSS URL is provided.
        assert url == "ws://dummy-wss-url", f"Expected ws://dummy-wss-url, got {url}"
        # Return a fake browser instance.
        return "fake-wss-browser"
class FakePlaywrightWSS:
    def __init__(self):
        self.chromium = FakeChromiumWSS()
    async def stop(self):
        # Fake cleanup does nothing.
        pass
class FakeAsyncPlaywrightWSS:
    async def start(self):
        # Return our fake playwright instance for the WSS simulation.
        return FakePlaywrightWSS()
def fake_async_playwright_wss():
    # This function replaces async_playwright in the Browser module for the WSS branch.
    return FakeAsyncPlaywrightWSS()
@pytest.mark.asyncio
async def test_get_playwright_browser_via_wss(monkeypatch):
    """
    Test that Browser.get_playwright_browser properly initializes a Playwright browser instance
    when a WSS URL is provided in the configuration.
    This test monkeypatches the async_playwright function to simulate connecting to a remote browser via WSS,
    and verifies that the returned browser is the fake one.
    """
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", fake_async_playwright_wss)
    config = BrowserConfig(wss_url="ws://dummy-wss-url")
    browser_instance = Browser(config=config)
    result = await browser_instance.get_playwright_browser()
    assert result == "fake-wss-browser"
    await browser_instance.close()