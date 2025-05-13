import asyncio
import subprocess

import psutil
import pytest
import requests

from browser_use.browser.browser import Browser, BrowserConfig, ProxySettings
from browser_use.browser.context import BrowserContext, BrowserContextConfig


@pytest.mark.asyncio
async def test_builtin_browser_launch(monkeypatch):
	"""
	Test that the standard browser is launched correctly:
	When no remote (cdp or wss) or chrome instance is provided, the Browser class uses _setup_builtin_browser.
	This test monkeypatches async_playwright to return dummy objects, and asserts that get_playwright_browser returns the expected DummyBrowser.
	"""

	class DummyBrowser:
		pass

	class DummyChromium:
		async def launch(self, headless, args, proxy=None, handle_sigterm=False, handle_sigint=False):
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(headless=True, disable_security=False, extra_browser_args=['--test'])
	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), 'Expected DummyBrowser from _setup_builtin_browser'
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
			assert endpoint_url == 'ws://dummy-cdp-url', 'The endpoint URL should match the configuration.'
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(cdp_url='ws://dummy-cdp-url')
	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), 'Expected DummyBrowser from _setup_cdp'
	await browser_obj.close()


@pytest.mark.asyncio
async def test_wss_browser_launch(monkeypatch):
	"""
	Test that when a WSS URL is provided in the configuration,
	the Browser uses setup_wss and returns the expected DummyBrowser.
	"""

	class DummyBrowser:
		pass

	class DummyChromium:
		async def connect(self, wss_url):
			assert wss_url == 'ws://dummy-wss-url', 'WSS URL should match the configuration.'
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(wss_url='ws://dummy-wss-url')
	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), 'Expected DummyBrowser from _setup_wss'
	await browser_obj.close()


@pytest.mark.asyncio
async def test_user_provided_browser_launch(monkeypatch):
	"""
	Test that when a browser_binary_path is provided the Browser class uses
	_setup_user_provided_browser branch and returns the expected DummyBrowser object
	by reusing an existing Chrome instance.
	"""

	# Dummy response for requests.get when checking chrome debugging endpoint.
	class DummyResponse:
		status_code = 200

	def dummy_get(url, timeout):
		if url == 'http://localhost:9222/json/version':
			return DummyResponse()
		raise requests.ConnectionError('Connection failed')

	monkeypatch.setattr(requests, 'get', dummy_get)

	class DummyBrowser:
		pass

	class DummyChromium:
		async def connect_over_cdp(self, endpoint_url, timeout=20000):
			assert endpoint_url == 'http://localhost:9222', "Endpoint URL must be 'http://localhost:9222'"
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(browser_binary_path='dummy/chrome', extra_browser_args=['--dummy-arg'])
	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), 'Expected DummyBrowser from _setup_user_provided_browser'
	await browser_obj.close()


@pytest.mark.asyncio
async def test_user_provided_browser_launch_on_custom_chrome_remote_debugging_port(monkeypatch):
	"""
	Test that when a browser_binary_path and chrome_remote_debugging_port are provided, the Browser class uses
	_setup_user_provided_browser branch and returns the expected DummyBrowser object
	by launching a new Chrome instance with --remote-debugging-port=chrome_remote_debugging_port argument.
	"""

	# Custom remote debugging port
	custom_chrome_remote_debugging_port = 9223

	# Dummy response for requests.get when checking chrome debugging endpoint.
	class DummyResponse:
		status_code = 200

	def dummy_get(url, timeout):
		if url == f'http://localhost:{custom_chrome_remote_debugging_port}/json/version':
			return DummyResponse()
		raise requests.ConnectionError('Connection failed')

	monkeypatch.setattr(requests, 'get', dummy_get)

	class DummyProcess:
		def __init__(self, *args, **kwargs):
			pass

	class DummySubProcess:
		pid = 1234

	async def dummy_create_subprocess_exec(browser_binary_path, *args, **kwargs):
		assert f'--remote-debugging-port={custom_chrome_remote_debugging_port}' in args, (
			f'Chrome must be started with with --remote-debugging-port={custom_chrome_remote_debugging_port} argument'
		)

		return DummySubProcess()

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', dummy_create_subprocess_exec)
	monkeypatch.setattr(psutil, 'Process', DummyProcess)

	class DummyBrowser:
		pass

	class DummyChromium:
		async def connect_over_cdp(self, endpoint_url, timeout=20000):
			assert endpoint_url == f'http://localhost:{custom_chrome_remote_debugging_port}', (
				f"Endpoint URL must be 'http://localhost:{custom_chrome_remote_debugging_port}'"
			)
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())

	config = BrowserConfig(
		browser_binary_path='dummy/chrome',
		chrome_remote_debugging_port=custom_chrome_remote_debugging_port,
		extra_browser_args=['--dummy-arg'],
	)

	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), (
		f'Expected DummyBrowser with remote debugging port {custom_chrome_remote_debugging_port} from _setup_user_provided_browser'
	)
	await browser_obj.close()


@pytest.mark.asyncio
async def test_builtin_browser_disable_security_args(monkeypatch):
	"""
	Test that the standard browser launch includes disable-security arguments when disable_security is True.
	This verifies that _setup_builtin_browser correctly appends the security disabling arguments along with
	the base arguments and any extra arguments provided.
	"""
	# These are the base arguments defined in _setup_builtin_browser.
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
		'--disable-features=IsolateOrigins,site-per-process',
	]
	# Additional arbitrary argument for testing extra args
	extra_args = ['--dummy-extra']

	class DummyBrowser:
		pass

	class DummyChromium:
		async def launch(self, headless, args, proxy=None, handle_sigterm=False, handle_sigint=False):
			# Expected args is the base args plus disable security args and the extra args.
			expected_args = base_args + disable_security_args + extra_args
			assert headless is True, 'Expected headless to be True'
			assert args == expected_args, f'Expected args {expected_args}, but got {args}'
			assert proxy is None, 'Expected proxy to be None'
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(headless=True, disable_security=True, extra_browser_args=extra_args)
	browser_obj = Browser(config=config)
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), (
		'Expected DummyBrowser from _setup_builtin_browser with disable_security active'
	)
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
	assert isinstance(context, BrowserContext), 'Expected new_context to return an instance of BrowserContext'
	assert context.browser is browser_obj, "Expected the context's browser attribute to be the Browser instance"
	assert context.config == custom_context_config, "Expected the context's config attribute to be the provided config"
	await browser_obj.close()


@pytest.mark.asyncio
async def test_user_provided_browser_launch_failure(monkeypatch):
	"""
	Test that when a Chrome instance cannot be started or connected to,
	the Browser._setup_user_provided_browser branch eventually raises a RuntimeError.
	We simulate failure by:
	  - Forcing requests.get to always raise a ConnectionError (so no existing instance is found).
	  - Monkeypatching subprocess.Popen to do nothing.
	  - Replacing asyncio.sleep to avoid delays.
	  - Having the dummy playwright's connect_over_cdp method always raise an Exception.
	"""

	def dummy_get(url, timeout):
		raise requests.ConnectionError('Simulated connection failure')

	monkeypatch.setattr(requests, 'get', dummy_get)
	monkeypatch.setattr(subprocess, 'Popen', lambda args, stdout, stderr: None)

	async def fake_sleep(seconds):
		return

	monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

	class DummyChromium:
		async def connect_over_cdp(self, endpoint_url, timeout=20000):
			raise Exception('Connection failed simulation')

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(browser_binary_path='dummy/chrome', extra_browser_args=['--dummy-arg'])
	browser_obj = Browser(config=config)
	with pytest.raises(RuntimeError, match='To start chrome in Debug mode'):
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
		async def launch(self, headless, args, proxy=None, handle_sigterm=False, handle_sigint=False):
			return DummyBrowser()

	class DummyPlaywright:
		def __init__(self):
			self.chromium = DummyChromium()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	config = BrowserConfig(headless=True, disable_security=False, extra_browser_args=['--test'])
	browser_obj = Browser(config=config)
	first_browser = await browser_obj.get_playwright_browser()
	second_browser = await browser_obj.get_playwright_browser()
	assert first_browser is second_browser, 'Expected the browser to be cached and reused across calls.'
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
			raise Exception('Close error simulation')

	class DummyPlaywrightWithError:
		async def stop(self):
			raise Exception('Stop error simulation')

	config = BrowserConfig()
	browser_obj = Browser(config=config)
	browser_obj.playwright_browser = DummyBrowserWithError()
	browser_obj.playwright = DummyPlaywrightWithError()
	await browser_obj.close()
	assert browser_obj.playwright_browser is None, 'Expected playwright_browser to be None after close'
	assert browser_obj.playwright is None, 'Expected playwright to be None after close'


@pytest.mark.asyncio
async def test_standard_browser_launch_with_proxy(monkeypatch):
	"""
	Test that when a proxy is provided in the BrowserConfig, the _setup_builtin_browser method
	correctly passes the proxy parameter to the playwright.chromium.launch method.
	This test sets up a dummy async_playwright context and verifies that the dummy proxy is received.
	"""

	class DummyBrowser:
		pass

	# Create a dummy proxy settings instance.
	dummy_proxy = ProxySettings(server='http://dummy.proxy')

	class DummyChromium:
		async def launch(self, headless, args, proxy=None, handle_sigterm=False, handle_sigint=False):
			# Assert that the proxy passed equals the dummy proxy provided in the configuration.
			assert isinstance(proxy, dict) and proxy['server'] == 'http://dummy.proxy', (
				f'Expected proxy {dummy_proxy} but got {proxy}'
			)
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
	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())
	# Create a BrowserConfig with the dummy proxy.
	config = BrowserConfig(headless=False, disable_security=False, proxy=dummy_proxy)
	browser_obj = Browser(config=config)
	# Call get_playwright_browser and verify that the returned browser is as expected.
	result_browser = await browser_obj.get_playwright_browser()
	assert isinstance(result_browser, DummyBrowser), 'Expected DummyBrowser from _setup_builtin_browser with proxy provided'
	await browser_obj.close()


@pytest.mark.asyncio
async def test_browser_window_size(monkeypatch):
	"""
	Test that when window_width and window_height are provided in BrowserContextConfig,
	they're properly converted to a dictionary when passed to Playwright.
	"""

	class DummyPage:
		def __init__(self):
			self.url = 'about:blank'

		async def goto(self, url):
			pass

		async def wait_for_load_state(self, state):
			pass

		async def title(self):
			return 'Test Page'

		async def bring_to_front(self):
			pass

		async def evaluate(self, script):
			return True

		def is_closed(self):
			return False

	class DummyContext:
		def __init__(self):
			self.pages = [DummyPage()]
			self.tracing = self

		async def new_page(self):
			return DummyPage()

		async def add_init_script(self, script):
			pass

		async def start(self):
			pass

		async def stop(self, path=None):
			pass

		def on(self, event, handler):
			pass

		async def close(self):
			pass

		async def grant_permissions(self, permissions, origin=None):
			pass

	class DummyBrowser:
		def __init__(self):
			self.contexts = []

		async def new_context(self, **kwargs):
			# Assert that record_video_size is a dictionary with expected values
			assert isinstance(kwargs['record_video_size'], dict), (
				f'Expected record_video_size to be a dictionary, got {type(kwargs["record_video_size"])}'
			)
			assert kwargs['record_video_size']['width'] == 1280, (
				f'Expected width to be 1280, got {kwargs["record_video_size"].get("width")}'
			)
			assert kwargs['record_video_size']['height'] == 1100, (
				f'Expected height to be 1100, got {kwargs["record_video_size"].get("height")}'
			)

			context = DummyContext()
			self.contexts.append(context)
			return context

		async def close(self):
			pass

	class DummyPlaywright:
		def __init__(self):
			self.chromium = self

		async def launch(self, **kwargs):
			return DummyBrowser()

		async def stop(self):
			pass

	class DummyAsyncPlaywrightContext:
		async def start(self):
			return DummyPlaywright()

	# Monkeypatch async_playwright to return our dummy async playwright context
	monkeypatch.setattr('browser_use.browser.browser.async_playwright', lambda: DummyAsyncPlaywrightContext())

	# Create browser with default config
	browser_obj = Browser()

	# Get browser instance
	playwright_browser = await browser_obj.get_playwright_browser()

	# Create context config with specific window size
	context_config = BrowserContextConfig(window_width=1280, window_height=1100)

	# Create browser context - this will test if window dimensions are properly converted
	browser_context = BrowserContext(browser=browser_obj, config=context_config)
	await browser_context._initialize_session()

	# Clean up
	await browser_context.close()
	await browser_obj.close()
