"""
Example script demonstrating the browser_window_size feature.
This script shows how to set a custom window size for the browser.
"""

import asyncio
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig, BrowserContextWindowSize


async def main():
	"""Demonstrate setting a custom browser window size"""
	# Create a browser with a specific window size
	window_size = BrowserContextWindowSize(width=800, height=400)  # Small size to clearly demonstrate the fix
	config = BrowserContextConfig(browser_window_size=window_size)

	browser = Browser(
		config=BrowserConfig(
			headless=False,  # Use non-headless mode to see the window
		)
	)

	try:
		# Create a browser context
		browser_context = await browser.new_context(config=config)

		# Get the current page
		page = await browser_context.get_current_page()

		# Navigate to a test page
		await page.goto('https://example.com')

		# Wait a bit to see the window
		await asyncio.sleep(2)

		# Get the actual viewport size using JavaScript
		viewport_size = await page.evaluate("""
            () => {
                return {
                    width: window.innerWidth,
                    height: window.innerHeight
                }
            }
        """)

		print(f'Configured window size: {window_size.model_dump()}')
		print(f'Actual viewport size: {viewport_size}')

		# Wait a bit more to see the window
		await asyncio.sleep(3)

	finally:
		# Close the browser
		await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
