import asyncio
import pytest
import requests
import subprocess
from browser_use.browser.browser import (
    Browser,
    BrowserConfig,
    logger,
)
from browser_use.browser.context import (
    BrowserContext,
    BrowserContextConfig,
)


class DummyBrowser:

    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class DummyChromium:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def launch(self, headless, args, proxy):
        return self.dummy_browser


class DummyPlaywright:

    def __init__(self, dummy_browser):
        self.chromium = DummyChromium(dummy_browser)

    async def stop(self):
        pass


class DummyAsyncPlaywright:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def start(self):
        return DummyPlaywright(self.dummy_browser)


@pytest.mark.asyncio
async def test_standard_browser_launch(monkeypatch):
    """
    Test that the Browser using standard launch configuration returns a dummy
    browser instance via the _setup_standard_browser branch and properly closes it.
    """
    dummy_browser = DummyBrowser()
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncPlaywright(dummy_browser),
    )
    config = BrowserConfig(headless=True)
    browser_instance = Browser(config)
    result = await browser_instance.get_playwright_browser()
    assert (
        result is dummy_browser
    ), "Expected the dummy browser instance to be returned."
    await browser_instance.close()
    assert (
        dummy_browser.closed
    ), "Dummy browser should be marked as closed after calling close()."


class DummyCDPChromium:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def connect_over_cdp(self, cdp_url, timeout=None):
        if cdp_url != "http://dummy:9222":
            raise ValueError("Unexpected CDP URL")
        return self.dummy_browser


class DummyCDPPlaywright:

    def __init__(self, dummy_browser):
        self.chromium = DummyCDPChromium(dummy_browser)

    async def stop(self):
        pass


class DummyAsyncCDPPlaywright:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def start(self):
        return DummyCDPPlaywright(self.dummy_browser)


@pytest.mark.asyncio
async def test_cdp_browser_launch(monkeypatch):
    """
    Test that the Browser configured with a CDP URL uses the _setup_cdp branch,
    and returns the expected dummy browser instance. Verifies that close() properly
    marks the browser as closed.
    """
    dummy_browser = DummyBrowser()
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncCDPPlaywright(dummy_browser),
    )
    config = BrowserConfig(cdp_url="http://dummy:9222")
    browser_instance = Browser(config)
    result = await browser_instance.get_playwright_browser()
    assert (
        result is dummy_browser
    ), "Expected the dummy browser instance from CDP branch"
    await browser_instance.close()
    assert (
        dummy_browser.closed
    ), "Dummy browser should be marked as closed after calling close()"


class DummyWSSChromium:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def connect(self, wss_url):
        if wss_url != "ws://dummy-wss":
            raise ValueError("Unexpected WSS URL")
        return self.dummy_browser


class DummyWSSPlaywright:

    def __init__(self, dummy_browser):
        self.chromium = DummyWSSChromium(dummy_browser)

    async def stop(self):
        pass


class DummyAsyncWSSPlaywright:

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser

    async def start(self):
        return DummyWSSPlaywright(self.dummy_browser)


@pytest.mark.asyncio
async def test_wss_browser_launch(monkeypatch):
    """
    Test that the Browser configured with a WSS URL uses the _setup_wss branch.
    This verifies that the dummy browser instance is returned and later closed.
    """
    dummy_browser = DummyBrowser()
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncWSSPlaywright(dummy_browser),
    )
    config = BrowserConfig(wss_url="ws://dummy-wss")
    browser_instance = Browser(config)
    result = await browser_instance.get_playwright_browser()
    assert (
        result is dummy_browser
    ), "Expected the dummy browser instance from the WSS branch."
    await browser_instance.close()
    assert (
        dummy_browser.closed
    ), "Dummy browser should be marked as closed after calling close()."


@pytest.mark.asyncio
async def test_chrome_instance_browser_launch(monkeypatch):
    """
    Test that the Browser configured with a chrome_instance_path uses the _setup_browser_with_instance branch.
    It simulates a delayed start of a Chrome instance by:
      - Monkey-patching requests.get to initially fail, then succeed.
      - Monkey-patching subprocess.Popen to simulate launching a new Chrome instance.
      - Using a dummy async_playwright that returns a dummy browser via chromium.connect_over_cdp.
    Verifies that the dummy browser instance is returned and closed properly.
    """
    dummy_browser = DummyBrowser()
    counter = {"calls": 0}

    def dummy_get(url, timeout):
        if url == "http://localhost:9222/json/version":
            if counter["calls"] < 2:
                counter["calls"] += 1
                raise requests.ConnectionError("Simulated connection error")
            else:

                class DummyResponse:
                    status_code = 200

                return DummyResponse()
        raise ValueError("Unexpected URL")

    monkeypatch.setattr(requests, "get", dummy_get)
    monkeypatch.setattr(subprocess, "Popen", lambda args, stdout, stderr: None)

    class DummyCDPChromePlaywright:

        def __init__(self, dummy_browser):
            self.chromium = self.DummyChromium(dummy_browser)

        class DummyChromium:

            def __init__(self, dummy_browser):
                self.dummy_browser = dummy_browser

            async def connect_over_cdp(self, endpoint_url, timeout):
                if endpoint_url != "http://localhost:9222":
                    raise ValueError("Unexpected endpoint URL")
                return self.dummy_browser

        async def stop(self):
            pass

    class DummyAsyncCDPChromePlaywright:

        def __init__(self, dummy_browser):
            self.dummy_browser = dummy_browser

        async def start(self):
            return DummyCDPChromePlaywright(self.dummy_browser)

    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncCDPChromePlaywright(dummy_browser),
    )
    config = BrowserConfig(chrome_instance_path="dummy_path")
    browser_instance = Browser(config)
    result = await browser_instance.get_playwright_browser()
    assert (
        result is dummy_browser
    ), "Expected dummy browser instance from chrome_instance branch"
    await browser_instance.close()
    assert (
        dummy_browser.closed
    ), "Dummy browser should be marked as closed after calling close()"


class DummyBrowserError:

    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True
        raise Exception("Simulated close error")


class DummyErrorChromium:

    def __init__(self, dummy_browser_error):
        self.dummy_browser_error = dummy_browser_error

    async def launch(self, headless, args, proxy):
        return self.dummy_browser_error


class DummyErrorPlaywright:

    def __init__(self, dummy_browser_error):
        self.chromium = DummyErrorChromium(dummy_browser_error)

    async def stop(self):
        raise Exception("Simulated stop error")


class DummyAsyncErrorPlaywright:

    def __init__(self, dummy_browser_error):
        self.dummy_browser_error = dummy_browser_error

    async def start(self):
        return DummyErrorPlaywright(self.dummy_browser_error)


@pytest.mark.asyncio
async def test_close_error_handling(monkeypatch):
    """
    Test that Browser.close() gracefully handles exceptions
    raised during the close() of the underlying browser and stop()
    of playwright. The test verifies that no exception is propagated and
    that the browser instance attributes are set to None.
    """
    dummy_browser_error = DummyBrowserError()
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncErrorPlaywright(dummy_browser_error),
    )
    config = BrowserConfig(headless=True)
    browser_instance = Browser(config)
    result = await browser_instance.get_playwright_browser()
    assert (
        result is dummy_browser_error
    ), "Expected the dummy browser error object to be returned."
    await browser_instance.close()
    assert (
        browser_instance.playwright is None
    ), "Expected playwright to be None after close()"
    assert (
        browser_instance.playwright_browser is None
    ), "Expected playwright_browser to be None after close()"
    assert (
        dummy_browser_error.closed
    ), "Expected the dummy browser error instance to be marked closed"


@pytest.mark.asyncio
async def test_new_context(monkeypatch):
    """
    Test that the new_context method returns a BrowserContext with the correct configuration.
    This verifies that a BrowserContext instance is created with the proper browser reference and config.
    """
    config = BrowserConfig(headless=True)
    browser_instance = Browser(config)
    custom_context_config = BrowserContextConfig()
    context = await browser_instance.new_context(custom_context_config)
    assert isinstance(context, BrowserContext), "Expected a BrowserContext instance"
    assert (
        context.browser is browser_instance
    ), "Expected the context to hold the original browser instance"
    assert (
        context.config == custom_context_config
    ), "Expected the context configuration to match the passed config"
    await browser_instance.close()


@pytest.mark.asyncio
async def test_get_browser_caching(monkeypatch):
    """
    Test that multiple calls to get_playwright_browser() return the same cached browser instance,
    and that the browser initialization (_init) is only performed once.
    """
    dummy_browser = DummyBrowser()
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyAsyncPlaywright(dummy_browser),
    )
    config = BrowserConfig(headless=True)
    browser_instance = Browser(config)
    call_count = {"count": 0}
    original_init = browser_instance._init

    async def fake_init():
        call_count["count"] += 1
        return await original_init()

    browser_instance._init = fake_init
    instance1 = await browser_instance.get_playwright_browser()
    instance2 = await browser_instance.get_playwright_browser()
    assert call_count["count"] == 1, "Expected _init to be called only once."
    assert (
        instance1 is instance2
    ), "Expected both calls to return the same browser instance."
    await browser_instance.close()


class RecordingDummyChromium:
    """Dummy Chromium that records launch arguments for verifying disable_security settings."""

    def __init__(self, dummy_browser):
        self.dummy_browser = dummy_browser
        self.launch_args = None
        self.launch_headless = None
        self.launch_proxy = None

    async def launch(self, headless, args, proxy):
        self.launch_headless = headless
        self.launch_args = args
        self.launch_proxy = proxy
        return self.dummy_browser


class RecordingDummyPlaywright:
    """Dummy Playwright that uses the recording dummy Chromium."""

    def __init__(self, dummy_browser, recorder):
        self.chromium = recorder

    async def stop(self):
        pass


class RecordingDummyAsyncPlaywright:
    """Dummy async_playwright that returns a RecordingDummyPlaywright."""

    def __init__(self, dummy_browser, recorder):
        self.dummy_browser = dummy_browser
        self.recorder = recorder

    async def start(self):
        return RecordingDummyPlaywright(self.dummy_browser, self.recorder)


@pytest.mark.asyncio
async def test_disable_security_args_when_disabled(monkeypatch):
    """
    Test that when disable_security is set to False, the disable security arguments are not
    included in the browser launch arguments. It verifies that only the standard arguments and
    extra_chromium_args are passed.
    """
    dummy_browser = object()
    recorder = RecordingDummyChromium(dummy_browser)

    def dummy_async_playwright():
        return RecordingDummyAsyncPlaywright(dummy_browser, recorder)

    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright", dummy_async_playwright
    )
    custom_extra = ["--custom-arg"]
    config = BrowserConfig(
        headless=True, disable_security=False, extra_chromium_args=custom_extra
    )
    browser_instance = Browser(config)
    browser_returned = await browser_instance.get_playwright_browser()
    expected_basic_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--disable-background-timer-throttling",
        "--disable-popup-blocking",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-window-activation",
        "--disable-focus-on-load",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-startup-window",
        "--window-position=0,0",
        "--enable-experimental-extension-apis",
    ]
    expected_args = expected_basic_args + [] + custom_extra
    assert (
        recorder.launch_args == expected_args
    ), "Launch args should not include disable security args when disable_security is False"
    assert (
        recorder.launch_headless is True
    ), "Headless value should be True as set in config"
    await browser_instance.close()


class DummyErrorStandardChromium:

    async def launch(self, headless, args, proxy):
        raise Exception("Simulated launch error in standard launch")


class DummyErrorStandardPlaywright:

    def __init__(self):
        self.chromium = DummyErrorStandardChromium()

    async def stop(self):
        pass


class DummyErrorAsyncStandardPlaywright:

    async def start(self):
        return DummyErrorStandardPlaywright()


@pytest.mark.asyncio
async def test_standard_browser_launch_error(monkeypatch):
    """
    Test that if launching a standard browser fails (simulated launch error),
    the get_playwright_browser method re-raises the exception.
    """
    monkeypatch.setattr(
        "browser_use.browser.browser.async_playwright",
        lambda: DummyErrorAsyncStandardPlaywright(),
    )
    config = BrowserConfig(headless=True)
    browser_instance = Browser(config)
    with pytest.raises(Exception, match="Simulated launch error in standard launch"):
        await browser_instance.get_playwright_browser()
