"""
Examples demonstrating browser window sizing features.

This example shows how to:
1. Set a custom window size for the browser
2. Verify the actual viewport dimensions
3. Use the no_viewport option
"""

import asyncio
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from browser_use.browser import BrowserProfile, BrowserSession


async def example_custom_window_size():
	"""Example 1: Setting a custom browser window size"""
	print('\n=== Example 1: Custom Window Size ===')

	# Create a browser profile with a specific window size
	profile = BrowserProfile(
		window_size={'width': 800, 'height': 600},  # Small size for demonstration
		# **playwright.devices['iPhone 13']         # or you can use a playwright device profile
		# device_scale_factor=1.0,                  # change to 2~3 to emulate a high-DPI display for high-res screenshots
		# viewport={'width': 800, 'height': 600},   # set the viewport (aka content size)
		# screen={'width': 800, 'height': 600},     # hardware display size to report to websites via JS
		headless=False,  # Use non-headless mode to see the window
	)

	browser_session = None

	try:
		# Initialize and start the browser session
		browser_session = BrowserSession(
			browser_profile=profile,
		)
		await browser_session.start()

		# Get the current page
		page = await browser_session.get_current_page()

		# Navigate to a test page
		await page.goto('https://example.com', wait_until='domcontentloaded')

		# Wait a bit to see the window
		await asyncio.sleep(1)

		# Get the actual viewport size using JavaScript
		actual_content_size = await page.evaluate("""() => ({width: window.innerWidth, height: window.innerHeight})""")

		if profile.viewport:
			expected_page_size = profile.viewport
		elif profile.window_size:
			expected_page_size = {
				'width': profile.window_size['width'],
				'height': profile.window_size['height'] - 87,
			}  # 87px is the height of the navbar, title, rim ish
		_log_size = lambda size: f'{size["width"]}x{size["height"]}px'
		print(f'Expected {_log_size(expected_page_size)} vs actual {_log_size(actual_content_size)}')

		# Validate the window size
		validate_window_size(expected_page_size, actual_content_size)

		# Wait a bit more to see the window
		await asyncio.sleep(2)

	except Exception as e:
		print(f'Error in example 1: {e}')

	finally:
		# Close resources
		if browser_session:
			await browser_session.stop()


async def example_no_viewport_option():
	"""Example 2: Testing browser window sizing with no_viewport option"""
	print('\n=== Example 2: Window Sizing with no_viewport=False ===')

	profile = BrowserProfile(window_size={'width': 1440, 'height': 900}, no_viewport=False, headless=False)

	browser_session = None

	try:
		browser_session = BrowserSession(browser_profile=profile)
		await browser_session.start()

		page = await browser_session.get_current_page()
		await page.goto('https://example.com')
		await asyncio.sleep(1)

		# Get viewport size (inner dimensions)
		viewport = await page.evaluate('() => ({width: window.innerWidth, height: window.innerHeight})')
		print(f'Configured size: width={profile.window_size["width"]}, height={profile.window_size["height"]}')
		print(f'Actual viewport size: {viewport}')

		# Get the actual window size (outer dimensions)
		window_size = await page.evaluate("""
			() => ({
				width: window.outerWidth,
				height: window.outerHeight
			})
		""")
		print(f'Actual window size (outer): {window_size}')

		await asyncio.sleep(2)

	except Exception as e:
		print(f'Error in example 2: {e}')

	finally:
		if browser_session:
			await browser_session.stop()


def validate_window_size(configured: dict[str, Any], actual: dict[str, Any]) -> None:
	"""Compare configured window size with actual size and report differences"""
	# Allow for small differences due to browser chrome, scrollbars, etc.
	width_diff = abs(configured['width'] - actual['width'])
	height_diff = abs(configured['height'] - actual['height'])

	# Tolerance of 5% or 20px, whichever is greater
	width_tolerance = max(configured['width'] * 0.05, 20)
	height_tolerance = max(configured['height'] * 0.05, 20)

	if width_diff > width_tolerance or height_diff > height_tolerance:
		print(f'⚠️  WARNING: Significant difference between expected and actual page size! ±{width_diff}x{height_diff}px')
		raise Exception('Window size validation failed')
	else:
		print('✅ Window size validation passed: actual size matches configured size within tolerance')


async def main():
	"""Run all window sizing examples"""
	print('Browser Window Sizing Examples')
	print('==============================')

	# Run example 1
	await example_custom_window_size()

	# Run example 2
	await example_no_viewport_option()

	print('\n✅ All examples completed!')


if __name__ == '__main__':
	asyncio.run(main())
