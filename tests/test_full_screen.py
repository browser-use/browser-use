import asyncio

import pytest
from playwright.async_api import async_playwright


@pytest.mark.parametrize(
	'start_fullscreen,maximize',
	[
		(True, True),
		(True, False),
		(False, True),
		(False, False),
	],
)
async def test_full_screen(start_fullscreen: bool, maximize: bool):
	async with async_playwright() as p:
		browser = await p.chromium.launch(
			headless=False,
			args=['--start-maximized'],
		)
		context = await browser.new_context(no_viewport=True, viewport=None)
		page = await context.new_page()
		await page.goto('https://google.com')

		await asyncio.sleep(10)
		await browser.close()


if __name__ == '__main__':
	asyncio.run(test_full_screen(False, False))
