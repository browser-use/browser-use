import asyncio

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig, BrowserContextWindowSize


async def test():
	print('Testing browser window sizing with no_viewport=False...')
	browser = Browser(BrowserConfig(headless=False))
	context_config = BrowserContextConfig(browser_window_size=BrowserContextWindowSize(width=1440, height=900), no_viewport=False)
	browser_context = await browser.new_context(config=context_config)
	page = await browser_context.get_current_page()
	await page.goto('https://example.com')
	await asyncio.sleep(2)
	viewport = await page.evaluate('() => ({width: window.innerWidth, height: window.innerHeight})')
	print('Configured size: width=1440, height=900')
	print(f'Actual viewport size: {viewport}')

	# Get the actual window size
	window_size = await page.evaluate("""
        () => ({
            width: window.outerWidth,
            height: window.outerHeight
        })
    """)
	print(f'Actual window size: {window_size}')

	await browser_context.close()
	await browser.close()


if __name__ == '__main__':
	asyncio.run(test())
