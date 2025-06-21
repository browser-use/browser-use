import asyncio
import base64

import pytest

from browser_use.browser import BrowserProfile, BrowserSession


async def test_take_full_page_screenshot():
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True))
	await browser_session.start()
	try:
		page = await browser_session.get_current_page()
		# Go to a test page
		await page.goto('https://example.com')

		await asyncio.sleep(3)
		# Take full page screenshot
		screenshot_b64 = await browser_session.take_screenshot(full_page=True)
		await asyncio.sleep(3)
		# Verify screenshot is not empty and is valid base64
		assert screenshot_b64 is not None
		assert isinstance(screenshot_b64, str)
		assert len(screenshot_b64) > 0

		# Test we can decode the base64 string
		try:
			base64.b64decode(screenshot_b64)
		except Exception as e:
			pytest.fail(f'Failed to decode base64 screenshot: {str(e)}')
	finally:
		await browser_session.stop()


if __name__ == '__main__':
	asyncio.run(test_take_full_page_screenshot())
