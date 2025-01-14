import base64

import pytest

from browser_use.browser.browser import Browser, BrowserConfig


@pytest.fixture
async def browser():
	browser_service = Browser(config=BrowserConfig(headless=True))
	yield browser_service

	await browser_service.close()


# @pytest.mark.skip(reason='takes too long')
def test_take_full_page_screenshot(browser):
	# Go to a test page
	browser.go_to_url('https://example.com')

	# Take full page screenshot
	screenshot_b64 = browser.take_screenshot(full_page=True)

	# Verify screenshot is not empty and is valid base64
	assert screenshot_b64 is not None
	assert isinstance(screenshot_b64, str)
	assert len(screenshot_b64) > 0

	# Test we can decode the base64 string
	try:
		base64.b64decode(screenshot_b64)
	except Exception as e:
		pytest.fail(f'Failed to decode base64 screenshot: {str(e)}')


if __name__ == '__main__':
	test_take_full_page_screenshot(Browser(config=BrowserConfig(headless=False)))
