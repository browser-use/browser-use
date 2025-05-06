import asyncio

import pytest
from patchright.async_api import async_playwright


@pytest.mark.asyncio
async def test_patchright_launch_and_close():
	async with async_playwright() as p:
		browser = await p.chromium.launch(headless=True)
		context = await browser.new_context()
		page = await context.new_page()

		await page.goto('https://example.com')
		title = await page.title()
		assert 'Example Domain' in title, "Expected 'Example Domain' in page title"

		await browser.close()


if __name__ == '__main__':
	asyncio.run(test_patchright_launch_and_close())
