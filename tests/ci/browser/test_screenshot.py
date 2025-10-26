import pytest

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.fixture(scope='function')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


@pytest.mark.asyncio
async def test_basic_screenshots(browser_session: BrowserSession, httpserver):
	"""Navigate to a local page and ensure screenshot helpers return bytes."""

	html = """
    <html><body><h1 id='title'>Hello</h1><p>Screenshot demo.</p></body></html>
    """
	httpserver.expect_request('/demo').respond_with_data(html, content_type='text/html')
	url = httpserver.url_for('/demo')

	nav = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
	await nav

	data = await browser_session.take_screenshot(full_page=False)
	assert data, 'Viewport screenshot returned no data'

	element = await browser_session.screenshot_element('h1')
	assert element, 'Element screenshot returned no data'
