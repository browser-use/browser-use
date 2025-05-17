import pytest

from browser_use.browser import BrowserProfile, BrowserSession


@pytest.mark.asyncio
async def test_builtin_browser_launch(monkeypatch):
	"""
	Test that the standard browser is launched correctly.
	This test monkeypatches async_playwright to return dummy objects, and asserts that BrowserSession.initialize() returns the expected browser.
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

	monkeypatch.setattr('browser_use.browser.session.async_playwright', lambda: DummyAsyncPlaywrightContext())
	session = BrowserSession(headless=True, disable_security=False, extra_launch_args=['--test'])
	await session.initialize()
	assert isinstance(session.browser, DummyBrowser), 'Expected DummyBrowser from _launch_browser'
	await session.close()


@pytest.mark.asyncio
async def test_new_context_creation():
	"""
	Test that the BrowserSession is initialized with the correct attributes.
	This verifies that the BrowserSession is initialized with the provided profile configuration.
	"""
	profile = BrowserProfile()
	session = BrowserSession(profile=profile)
	await session.initialize()
	assert session.profile == profile, "Expected the session's profile to be the provided profile"
	await session.close()
