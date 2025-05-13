"""
Example script demonstrating the browser_window_size feature.
This script shows how to set a custom window size for the browser.
"""

import asyncio
import sys
from typing import Any

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig


async def main():
	"""Demonstrate setting a custom browser window size"""
	# Create a browser with a specific window size
	config = BrowserContextConfig(window_width=800, window_height=400)  # Small size to clearly demonstrate the fix

	browser = None
	browser_context = None

	try:
		# Initialize the browser with error handling
		try:
			browser = Browser(
				config=BrowserConfig(
					headless=False,  # Use non-headless mode to see the window
				)
			)
		except Exception as e:
			print(f'Failed to initialize browser: {e}')
			return 1

		# Create a browser context
		try:
			browser_context = await browser.new_context(config=config)
		except Exception as e:
			print(f'Failed to create browser context: {e}')
			return 1

		# Get the current page
		page = await browser_context.get_current_page()

		# Navigate to a test page with error handling
		try:
			await page.goto('https://example.com')
			await page.wait_for_load_state('domcontentloaded')
		except Exception as e:
			print(f'Failed to navigate to example.com: {e}')
			print('Continuing with test anyway...')

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

		print(f'Configured window size: width={config.window_width}, height={config.window_height}')
		print(f'Actual viewport size: {viewport_size}')

		# Validate the window size
		validate_window_size({'width': config.window_width, 'height': config.window_height}, viewport_size)

		# Wait a bit more to see the window
		await asyncio.sleep(3)

		return 0

	except Exception as e:
		print(f'Unexpected error: {e}')
		return 1

	finally:
		# Close resources
		if browser_context:
			await browser_context.close()
		if browser:
			await browser.close()


def validate_window_size(configured: dict[str, Any], actual: dict[str, Any]) -> None:
	"""Compare configured window size with actual size and report differences"""
	# Allow for small differences due to browser chrome, scrollbars, etc.
	width_diff = abs(configured['width'] - actual['width'])
	height_diff = abs(configured['height'] - actual['height'])

	# Tolerance of 5% or 20px, whichever is greater
	width_tolerance = max(configured['width'] * 0.05, 20)
	height_tolerance = max(configured['height'] * 0.05, 20)

	if width_diff > width_tolerance or height_diff > height_tolerance:
		print('WARNING: Significant difference between configured and actual window size!')
		print(f'Width difference: {width_diff}px, Height difference: {height_diff}px')
	else:
		print('Window size validation passed: actual size matches configured size within tolerance')


if __name__ == '__main__':
	result = asyncio.run(main())
	sys.exit(result)
