import pytest

pytest.skip('TODO: fix - import error for async_playwright', allow_module_level=True)

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.types import async_playwright


async def test_connection_via_cdp():
	browser_session = BrowserSession(
		cdp_url='http://localhost:9898',
		browser_profile=BrowserProfile(
			headless=True,
			keep_alive=True,
		),
	)
	with pytest.raises(Exception) as e:
		await browser_session.start()

	# Assert on the exception value outside the context manager
	assert 'ECONNREFUSED' in str(e.value)

	playwright = await async_playwright().start()
	browser = await playwright.chromium.launch(args=['--remote-debugging-port=9898'])

	async with await browser_session.start():
		await browser_session.create_new_tab()

		assert (await browser_session.get_current_page()).url == 'about:blank'

		await browser.close()

	await browser_session.kill()
	await playwright.stop()
