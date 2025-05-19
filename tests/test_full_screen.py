import asyncio

from browser_use.driver import Driver


async def test_full_screen(start_fullscreen: bool, maximize: bool):
	async with Driver("playwright") as p:
		assert p.chromium is not None
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
