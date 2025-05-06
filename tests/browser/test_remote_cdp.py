import asyncio

from playwright.async_api import async_playwright


async def test_remote_cdp_connection():
	# Remote debugging URL - replace with actual if needed in local/dev
	cdp_url = 'http://localhost:9222'  # This port must be open in CI if testing real CDP

	async with async_playwright() as p:
		# Connect to a remote Chrome instance via CDP
		browser = await p.chromium.connect_over_cdp(cdp_url)
		contexts = browser.contexts
		if not contexts:
			context = await browser.new_context()
		else:
			context = contexts[0]

		page = await context.new_page()
		await page.goto('https://example.com')
		title = await page.title()

		assert 'Example Domain' in title, "Page title should contain 'Example Domain'"
		await browser.close()


if __name__ == '__main__':
	asyncio.run(test_remote_cdp_connection())
