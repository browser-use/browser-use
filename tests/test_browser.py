import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from browser_use.browser.browser import Browser, BrowserConfig
import subprocess
import requests
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_setup_cdp_without_url():
    """
    Test that _setup_cdp raises ValueError when the CDP URL is not provided in the configuration.
    """
    # Create a BrowserConfig with no CDP URL.
    config = BrowserConfig(cdp_url=None)
    browser_instance = Browser(config)
    
    # Create a dummy playwright object with mocked chromium.connect_over_cdp.
    playwright = MagicMock()
    playwright.chromium = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock()
    
    # Expect a ValueError since the config does not provide a valid CDP URL.
    with pytest.raises(ValueError, match="CDP URL is required"):
        await browser_instance._setup_cdp(playwright)
@pytest.mark.asyncio
async def test_setup_standard_browser_success():
    """
    Test that _setup_standard_browser launches a browser with the correct configuration.
    
    This test creates a BrowserConfig with a custom extra_chromium_arg, sets up a dummy
    playwright object with a mocked chromium.launch, and verifies that the launch method
    is called with the expected headless flag and arguments. It also confirms that the
    returned browser is the one provided by the mocked launch.
    """
    # Prepare a BrowserConfig with an extra argument.
    extra_arg = '--foo'
    config = BrowserConfig(headless=True, extra_chromium_args=[extra_arg])
    browser_instance = Browser(config)
    
    # Create a dummy playwright with a mocked chromium.launch.
    fake_browser = MagicMock(name="FakeBrowser")
    fake_playwright = MagicMock(name="FakePlaywright")
    fake_playwright.chromium = MagicMock(name="FakeChromium")
    fake_playwright.chromium.launch = AsyncMock(return_value=fake_browser)
    
    # Call _setup_standard_browser and capture the returned browser.
    result_browser = await browser_instance._setup_standard_browser(fake_playwright)
    
    # Verify that the launch method was called once.
    fake_playwright.chromium.launch.assert_awaited_once()
    
    # Extract the arguments used in the launch call.
    launch_call = fake_playwright.chromium.launch.call_args
    kwargs = launch_call.kwargs
    # Verify the headless flag matches our config.
    assert kwargs.get('headless') == True
    
    # Reconstruct the complete args list expected.
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
        '--window-position=0,0'
    ]
    disable_security_args = [
        '--disable-web-security',
        '--disable-site-isolation-trials',
        '--disable-features=IsolateOrigins,site-per-process'
    ]
    # The complete expected args concatenates the base args, disable security args, and extra args.
    expected_args = base_args + disable_security_args + [extra_arg]
    
    # Assert that all expected arguments are in the 'args' list.
    actual_args = kwargs.get('args')
    for arg in expected_args:
        assert arg in actual_args, f"Argument {arg} not found in launch args: {actual_args}"
    
    # Verify that the proxy parameter is passed as None.
    assert kwargs.get('proxy') is None
    
    # Finally, confirm that the resulting browser is the same as the fake_browser.
    assert result_browser is fake_browser
@pytest.mark.asyncio
async def test_setup_wss_success():
    """
    Test that _setup_wss returns a browser instance when provided with a valid WSS URL.
    This test creates a BrowserConfig with a valid wss_url and a dummy playwright object
    with a mocked chromium.connect method to simulate connecting to a remote browser.
    """
    # Prepare a BrowserConfig with a valid wss_url.
    wss_url = "ws://dummy-wss-url"
    config = BrowserConfig(wss_url=wss_url)
    browser_instance = Browser(config)
    
    # Create a dummy fake browser object.
    fake_browser = MagicMock(name="FakeBrowser")
    
    # Create a dummy playwright object with a mocked chromium.connect method.
    fake_playwright = MagicMock(name="FakePlaywright")
    fake_playwright.chromium = MagicMock(name="FakeChromium")
    fake_playwright.chromium.connect = AsyncMock(return_value=fake_browser)
    
    # Call _setup_wss and verify that it returns the fake_browser.
    result_browser = await browser_instance._setup_wss(fake_playwright)
    
    # Ensure that the chromium.connect was called with the correct wss_url.
    fake_playwright.chromium.connect.assert_awaited_once_with(wss_url)
    
    # Assert that the result is indeed our fake_browser.
    assert result_browser is fake_browser
@pytest.mark.asyncio
async def test_setup_browser_with_instance_success(monkeypatch):
    """
    Test that _setup_browser_with_instance starts a new Chrome instance (when none is initially running)
    and then successfully connects to it via CDP.
    """
    # Prepare a BrowserConfig with chrome_instance_path so that _setup_browser_with_instance is used.
    config = BrowserConfig(chrome_instance_path="dummy/chrome/path")
    browser_instance = Browser(config)
    # Create a fake browser to return when connecting.
    fake_browser = MagicMock(name="FakeBrowser")
    
    # Create a fake playwright with chromium.connect_over_cdp mocked.
    fake_playwright = MagicMock(name="FakePlaywright")
    fake_playwright.chromium = MagicMock(name="FakeChromium")
    fake_playwright.chromium.connect_over_cdp = AsyncMock(return_value=fake_browser)
    # Define a fake response object with status_code 200.
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
    # Create a counter to control the calls to requests.get.
    call_counter = {"count": 0}
    
    # Define a side effect function for requests.get:
    def fake_requests_get(url, timeout):
        # First call simulates a ConnectionError indicating no Chrome instance is running.
        if call_counter["count"] == 0:
            call_counter["count"] += 1
            raise requests.ConnectionError("No connection")
        # Second call simulates a successful response.
        else:
            return FakeResponse(status_code=200)
    # Patch requests.get with our side effect.
    monkeypatch.setattr(requests, "get", fake_requests_get)
    
    # Patch subprocess.Popen so that no actual subprocess is started.
    def fake_popen(args, stdout, stderr):
        return MagicMock()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    
    # Patch asyncio.sleep to yield control without actually delaying.
    async def fast_sleep(_):
        return
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    
    # Call _setup_browser_with_instance and verify that it returns the fake_browser.
    result_browser = await browser_instance._setup_browser_with_instance(fake_playwright)
    
    # Assert that playwright.chromium.connect_over_cdp was called with the expected endpoint.
    fake_playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        endpoint_url='http://localhost:9222',
        timeout=20000
    )
    
    # Assert that the result from _setup_browser_with_instance is indeed the fake_browser.
    assert result_browser is fake_browser
@pytest.mark.asyncio
async def test_close_calls_stop_and_browser_close():
    """
    Test that the close method awaits the browser's close and playwright's stop methods,
    and then resets both attributes to None.
    """
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Create fake async methods for playwright_browser.close and playwright.stop.
    fake_playwright_browser = AsyncMock()
    fake_playwright = AsyncMock()
    
    # Assign fake objects to the instance.
    browser_instance.playwright_browser = fake_playwright_browser
    browser_instance.playwright = fake_playwright
    
    # Call close and verify.
    await browser_instance.close()
    
    fake_playwright_browser.close.assert_awaited_once()
    fake_playwright.stop.assert_awaited_once()
    
    # Ensure that the attributes have been set to None after closing.
    assert browser_instance.playwright_browser is None
    assert browser_instance.playwright is None
@pytest.mark.asyncio
async def test_get_playwright_browser_returns_existing_browser(monkeypatch):
    """
    Test that get_playwright_browser returns the existing playwright_browser if already initialized,
    and does not call the _init method.
    """
    # Create a Browser instance with default configuration.
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Simulate an already initialized browser.
    fake_browser = MagicMock(name="FakeBrowser")
    browser_instance.playwright_browser = fake_browser
    
    # Patch the _init method to fail if it is called.
    async def dummy_init():
        raise RuntimeError("Dummy _init should not be called")
    monkeypatch.setattr(browser_instance, "_init", dummy_init)
    
    # Call get_playwright_browser and check that it returns the fake_browser.
    result = await browser_instance.get_playwright_browser()
    assert result == fake_browser
@pytest.mark.asyncio
async def test_new_context_returns_browser_context():
    """
    Test that new_context creates and returns a BrowserContext instance
    initialized with the provided BrowserContextConfig and associated with
    the Browser instance.
    """
    from browser_use.browser.browser import Browser, BrowserConfig
    # Create a Browser instance with a default configuration.
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Prepare a BrowserContextConfig.
    context_config = BrowserContextConfig()
    
    # Call new_context to obtain a BrowserContext.
    browser_context = await browser_instance.new_context(config=context_config)
    
    # Check that the returned object is an instance of BrowserContext.
    assert isinstance(browser_context, BrowserContext)
    
    # Ensure that the BrowserContext is associated with the same Browser instance.
    assert browser_context.browser is browser_instance
    
    # Ensure that the BrowserContext configuration matches the one provided.
    assert browser_context.config == context_config
@pytest.mark.asyncio
async def test_setup_browser_failure(monkeypatch):
    """
    Test that _setup_browser logs an error and re-raises the exception
    when _setup_standard_browser fails.
    """
    # Create a BrowserConfig with default values (so that _setup_standard_browser is called).
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Create a dummy playwright object as a MagicMock.
    fake_playwright = MagicMock()
    fake_playwright.chromium = MagicMock()
    
    # Monkey-patch _setup_standard_browser to simulate a failure.
    async def fake_standard_browser(playwright):
        raise Exception("Standard browser launch failed")
    monkeypatch.setattr(browser_instance, "_setup_standard_browser", fake_standard_browser)
    
    # Assert that _setup_browser raises the expected exception.
    with pytest.raises(Exception, match="Standard browser launch failed"):
        await browser_instance._setup_browser(fake_playwright)# No additional external imports are necessary; all imports (pytest, asyncio, MagicMock, etc.)
# used in this test are available from the original test file.
@pytest.mark.asyncio
async def test_get_playwright_browser_initializes_when_none(monkeypatch):
    """
    Test that get_playwright_browser calls _init when no browser instance is cached,
    and that the result is subsequently cached to avoid future calls to _init.
    """
    # Create a Browser instance with default configuration.
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Ensure no playwright_browser exists.
    browser_instance.playwright_browser = None
    
    # Create a fake browser instance to be returned by _init.
    fake_browser = MagicMock(name="FakeBrowser")
    
    # Flag to confirm that _init was called.
    init_called = False
    
    async def fake_init():
        nonlocal init_called
        init_called = True
        return fake_browser
     
    # Monkey-patch _init with our fake implementation.
    monkeypatch.setattr(browser_instance, "_init", fake_init)
    
    # Call get_playwright_browser, which should call fake_init.
    result = await browser_instance.get_playwright_browser()
    
    # Confirm that _init was called and the fake_browser is returned.
    assert init_called, "Expected _init to be called when playwright_browser is None"
    assert result is fake_browser, "Expected returned browser to be the fake_browser instance"
    
    # Reset the flag and call get_playwright_browser again, it should return the same instance
    init_called = False
    result2 = await browser_instance.get_playwright_browser()
    
    # Since playwright_browser is now cached, _init should not be called again.
    assert not init_called, "Expected _init not to be called when playwright_browser is already set"
    assert result2 is fake_browser, "Expected the cached browser instance to be returned on subsequent calls"
@pytest.mark.asyncio
async def test_get_playwright_browser_initializes_when_none(monkeypatch):
    """
    Test that get_playwright_browser calls _init when no browser instance is cached,
    and that the result is subsequently cached to avoid future calls to _init.
    
    The fake _init now updates self.playwright_browser before returning the fake browser.
    """
    # Create a Browser instance with default configuration.
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Ensure no playwright_browser exists.
    browser_instance.playwright_browser = None
    
    # Create a fake browser instance to be returned by _init.
    fake_browser = MagicMock(name="FakeBrowser")
    
    # Flag to confirm that _init was called.
    init_called = False
    
    async def fake_init():
        nonlocal init_called
        init_called = True
        # Update the cached browser instance as the real _init would do.
        browser_instance.playwright_browser = fake_browser
        return fake_browser
     
    # Monkey-patch _init with our fake implementation.
    monkeypatch.setattr(browser_instance, "_init", fake_init)
    
    # Call get_playwright_browser, which should call fake_init.
    result = await browser_instance.get_playwright_browser()
    
    # Confirm that _init was called and the fake_browser is returned.
    assert init_called, "Expected _init to be called when playwright_browser is None"
    assert result is fake_browser, "Expected returned browser to be the fake_browser instance"
    
    # Reset the flag and call get_playwright_browser again; it should return the cached fake_browser.
    init_called = False
    result2 = await browser_instance.get_playwright_browser()
    
    # Since playwright_browser is now cached, _init should not be called again.
    assert not init_called, "Expected _init not to be called when playwright_browser is already set"
    assert result2 is fake_browser, "Expected the cached browser instance to be returned on subsequent calls"import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from browser_use.browser.browser import Browser, BrowserConfig


@pytest.mark.asyncio
async def test_del_calls_close_with_no_running_loop(monkeypatch):
    """
    Test that the __del__ method calls asyncio.run(self.close())
    when the current event loop is not running. We simulate this scenario
    by monkey-patching asyncio.get_running_loop to return a fake loop with
    is_running() returning False and verifying that the fake_close method is called.
    """
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Flag to confirm that the close method is called.
    flag = {"close_called": False}
    
    async def fake_close():
        flag["close_called"] = True

    # Replace the instance's close method with our fake_close.
    browser_instance.close = fake_close

    # Create a fake loop that is not running.
    fake_loop = MagicMock()
    fake_loop.is_running.return_value = False

    # Monkey-patch asyncio.get_running_loop to return our fake loop.
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: fake_loop)

    # Manually call __del__ to trigger cleanup.
    browser_instance.__del__()

    # Because asyncio.run is used in the non-running loop branch, it will run our fake_close synchronously.
    assert flag["close_called"] is True
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from browser_use.browser.browser import Browser, BrowserConfig


@pytest.mark.asyncio
async def test_del_calls_close_with_no_running_loop(monkeypatch):
    """
    Test that the __del__ method calls asyncio.run(self.close())
    when the current event loop is not running.
    This test sets a dummy value for playwright_browser to force the cleanup branch,
    monkey-patches asyncio.get_running_loop to simulate a non-running loop,
    replaces the close method with a fake close, and verifies that it is executed.
    """
    # Create a Browser instance.
    config = BrowserConfig()
    browser_instance = Browser(config)
    
    # Set one of the attributes to a dummy value to trigger the cleanup in __del__.
    browser_instance.playwright_browser = MagicMock()
    
    # Flag to confirm that close is called.
    flag = {"close_called": False}
    
    async def fake_close():
        flag["close_called"] = True

    # Replace the instance's close method with our fake_close.
    browser_instance.close = fake_close
    
    # Create a fake loop that is not running.
    fake_loop = MagicMock()
    fake_loop.is_running.return_value = False
    
    # Monkey-patch asyncio.get_running_loop to return our fake loop.
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: fake_loop)
    
    # Manually call __del__ to trigger cleanup.
    browser_instance.__del__()
    
    # Assert that close was called.
    assert flag["close_called"] is True
