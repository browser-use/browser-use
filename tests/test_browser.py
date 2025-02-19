import asyncio
import pytest
import requests
import subprocess
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from playwright._impl._api_structures import ProxySettings

@pytest.mark.asyncio
async def test_standard_browser_launch(monkeypatch):
    """
    Test that the standard browser is launched correctly:
    When no remote (cdp or wss) or chrome instance is provided, the Browser class uses _setup_standard_browser.
    This test monkeypatches async_playwright to return dummy objects, and asserts that get_playwright_browser returns the expected DummyBrowser.
    """
    class DummyBrowser:
        pass
    class DummyChromium:
        async def launch(self, headless, args, proxy=None):
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(headless=True, disable_security=False, extra_chromium_args=["--test"])
    browser_obj = Browser(config=config)
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_standard_browser"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_cdp_browser_launch(monkeypatch):
    """
    Test that when a CDP URL is provided in the configuration, the Browser uses _setup_cdp 
    and returns the expected DummyBrowser.
    """
    class DummyBrowser:
        pass
    class DummyChromium:
        async def connect_over_cdp(self, endpoint_url, timeout=20000):
            assert endpoint_url == "ws://dummy-cdp-url", "The endpoint URL should match the configuration."
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(cdp_url="ws://dummy-cdp-url")
    browser_obj = Browser(config=config)
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_cdp"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_wss_browser_launch(monkeypatch):
    """
    Test that when a WSS URL is provided in the configuration,
    the Browser uses _setup_wss and returns the expected DummyBrowser.
    """
    class DummyBrowser:
        pass
    class DummyChromium:
        async def connect(self, wss_url):
            assert wss_url == "ws://dummy-wss-url", "WSS URL should match the configuration."
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(wss_url="ws://dummy-wss-url")
    browser_obj = Browser(config=config)
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_wss"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_chrome_instance_browser_launch(monkeypatch):
    """
    Test that when a chrome instance path is provided the Browser class uses 
    _setup_browser_with_instance branch and returns the expected DummyBrowser object
    by reusing an existing Chrome instance.
    """
    # Dummy response for requests.get when checking chrome debugging endpoint.
    class DummyResponse:
        status_code = 200
    def dummy_get(url, timeout):
        if url == "http://localhost:9222/json/version":
            return DummyResponse()
        raise requests.ConnectionError("Connection failed")
    monkeypatch.setattr(requests, "get", dummy_get)
    class DummyBrowser:
        pass
    class DummyChromium:
        async def connect_over_cdp(self, endpoint_url, timeout=20000):
            assert endpoint_url == "http://localhost:9222", "Endpoint URL must be 'http://localhost:9222'"
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(chrome_instance_path="dummy/chrome", extra_chromium_args=["--dummy-arg"])
    browser_obj = Browser(config=config)
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_browser_with_instance"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_standard_browser_disable_security_args(monkeypatch):
    """
    Test that the standard browser launch includes disable-security arguments when disable_security is True.
    This verifies that _setup_standard_browser correctly appends the security disabling arguments along with
    the base arguments and any extra arguments provided.
    """
    # These are the base arguments defined in _setup_standard_browser.
    base_args = [
        '--no-sandbox',
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--disable-background-timer-throttling',
        '--disable-popup-blocking',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-window-activation',
        '--disable-focus-on-load',
        '--no-first-run',
        '--no-default-browser-check',
        '--no-startup-window',
        '--window-position=0,0',
    ]
    # When disable_security is True, these arguments should be added.
    disable_security_args = [
        '--disable-web-security',
        '--disable-site-isolation-trials',
        '--disable-features=IsolateOrigins,site-per-process'
    ]
    # Additional arbitrary argument for testing extra args
    extra_args = ["--dummy-extra"]
    class DummyBrowser:
        pass
    class DummyChromium:
        async def launch(self, headless, args, proxy=None):
            # Expected args is the base args plus disable security args and the extra args.
            expected_args = base_args + disable_security_args + extra_args
            assert headless is True, "Expected headless to be True"
            assert args == expected_args, f"Expected args {expected_args}, but got {args}"
            assert proxy is None, "Expected proxy to be None"
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(headless=True, disable_security=True, extra_chromium_args=extra_args)
    browser_obj = Browser(config=config)
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_standard_browser with disable_security active"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_new_context_creation():
    """
    Test that the new_context method returns a BrowserContext with the correct attributes.
    This verifies that the BrowserContext is initialized with the provided Browser instance and configuration.
    """
    config = BrowserConfig()
    browser_obj = Browser(config=config)
    custom_context_config = BrowserContextConfig()
    context = await browser_obj.new_context(custom_context_config)
    assert isinstance(context, BrowserContext), "Expected new_context to return an instance of BrowserContext"
    assert context.browser is browser_obj, "Expected the context's browser attribute to be the Browser instance"
    assert context.config == custom_context_config, "Expected the context's config attribute to be the provided config"
    await browser_obj.close()
@pytest.mark.asyncio
async def test_chrome_instance_browser_launch_failure(monkeypatch):
    """
    Test that when a Chrome instance cannot be started or connected to,
    the Browser._setup_browser_with_instance branch eventually raises a RuntimeError.
    We simulate failure by:
      - Forcing requests.get to always raise a ConnectionError (so no existing instance is found).
      - Monkeypatching subprocess.Popen to do nothing.
      - Replacing asyncio.sleep to avoid delays.
      - Having the dummy playwright's connect_over_cdp method always raise an Exception.
    """
    def dummy_get(url, timeout):
        raise requests.ConnectionError("Simulated connection failure")
    monkeypatch.setattr(requests, "get", dummy_get)
    monkeypatch.setattr(subprocess, "Popen", lambda args, stdout, stderr: None)
    async def fake_sleep(seconds):
        return
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    class DummyChromium:
        async def connect_over_cdp(self, endpoint_url, timeout=20000):
            raise Exception("Connection failed simulation")
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(chrome_instance_path="dummy/chrome", extra_chromium_args=["--dummy-arg"])
    browser_obj = Browser(config=config)
    with pytest.raises(RuntimeError, match="To start chrome in Debug mode"):
        await browser_obj.get_playwright_browser()
    await browser_obj.close()
@pytest.mark.asyncio
async def test_get_playwright_browser_caching(monkeypatch):
    """
    Test that get_playwright_browser returns a cached browser instance.
    On the first call, the browser is initialized; on subsequent calls,
    the same instance is returned.
    """
    class DummyBrowser:
        pass
    class DummyChromium:
        async def launch(self, headless, args, proxy=None):
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    config = BrowserConfig(headless=True, disable_security=False, extra_chromium_args=["--test"])
    browser_obj = Browser(config=config)
    first_browser = await browser_obj.get_playwright_browser()
    second_browser = await browser_obj.get_playwright_browser()
    assert first_browser is second_browser, "Expected the browser to be cached and reused across calls."
    await browser_obj.close()
@pytest.mark.asyncio
async def test_close_error_handling(monkeypatch):
    """
    Test that the close method properly handles exceptions thrown by
    playwright_browser.close() and playwright.stop(), ensuring that the
    browser's attributes are set to None even if errors occur.
    """
    class DummyBrowserWithError:
        async def close(self):
            raise Exception("Close error simulation")
    class DummyPlaywrightWithError:
        async def stop(self):
            raise Exception("Stop error simulation")
    config = BrowserConfig()
    browser_obj = Browser(config=config)
    browser_obj.playwright_browser = DummyBrowserWithError()
    browser_obj.playwright = DummyPlaywrightWithError()
    await browser_obj.close()
    assert browser_obj.playwright_browser is None, "Expected playwright_browser to be None after close"
    assert browser_obj.playwright is None, "Expected playwright to be None after close"
@pytest.mark.asyncio
async def test_standard_browser_launch_with_proxy(monkeypatch):
    """
    Test that when a proxy is provided in the BrowserConfig, the _setup_standard_browser method
    correctly passes the proxy parameter to the playwright.chromium.launch method.
    This test sets up a dummy async_playwright context and verifies that the dummy proxy is received.
    """
    class DummyBrowser:
        pass
    # Create a dummy proxy settings instance.
    dummy_proxy = ProxySettings(server="http://dummy.proxy")
    class DummyChromium:
        async def launch(self, headless, args, proxy=None):
            # Assert that the proxy passed equals the dummy proxy provided in the configuration.
            assert proxy == dummy_proxy, f"Expected proxy {dummy_proxy} but got {proxy}"
            # We can also verify some base parameters if needed (headless, args) but our focus is proxy.
            return DummyBrowser()
    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        async def stop(self):
            pass
    class DummyAsyncPlaywrightContext:
        async def start(self):
            return DummyPlaywright()
    # Monkeypatch async_playwright to return our dummy async playwright context.
    monkeypatch.setattr("browser_use.browser.browser.async_playwright", lambda: DummyAsyncPlaywrightContext())
    # Create a BrowserConfig with the dummy proxy.
    config = BrowserConfig(headless=False, disable_security=False, proxy=dummy_proxy)
    browser_obj = Browser(config=config)
    # Call get_playwright_browser and verify that the returned browser is as expected.
    result_browser = await browser_obj.get_playwright_browser()
    assert isinstance(result_browser, DummyBrowser), "Expected DummyBrowser from _setup_standard_browser with proxy provided"
    await browser_obj.close()