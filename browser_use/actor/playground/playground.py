#!/usr/bin/env python3
"""
Playground script to test the browser-use actor API.

This script demonstrates:
- Starting a browser session
- Using the actor API to navigate and interact
- Finding elements, clicking, scrolling, JavaScript evaluation
- Testing most of the available methods
"""

import asyncio
import json
import logging

from browser_use import Browser

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
	"""Main playground function."""
	logger.info('🚀 Starting browser actor playground')

	# Create browser session
	browser = Browser()

	try:
		# Start the browser
		await browser.start()
		logger.info('✅ Browser session started')

		# Navigate to Wikipedia using integrated methods
		logger.info('📖 Navigating to Wikipedia...')
		page = await browser.new_page('https://en.wikipedia.org')

		# Get basic page info
		url = await page.get_url()
		title = await page.get_title()
		logger.info(f'📄 Page loaded: {title} ({url})')

		# Take a screenshot
		logger.info('📸 Taking initial screenshot...')
		screenshot_b64 = await page.screenshot()
		logger.info(f'📸 Screenshot captured: {len(screenshot_b64)} bytes')

		# Set viewport size
		logger.info('🖥️ Setting viewport to 1920x1080...')
		await page.set_viewport_size(1920, 1080)

		# Execute some JavaScript to count links
		logger.info('🔍 Counting article links using JavaScript...')
		js_code = """() => {
			// Find all article links on the page
			const links = Array.from(document.querySelectorAll('a[href*="/wiki/"]:not([href*=":"])'))
				.filter(link => !link.href.includes('Main_Page') && !link.href.includes('Special:'));
			
			return {
				total: links.length,
				sample: links.slice(0, 3).map(link => ({
					href: link.href,
					text: link.textContent.trim() 
				}))
			};
		}"""

		link_info = json.loads(await page.evaluate(js_code))
		logger.info(f'🔗 Found {link_info["total"]} article links')
		# Try to find and interact with links using CSS selector
		try:
			# Find article links on the page
			links = await page.get_elements_by_css_selector('a[href*="/wiki/"]:not([href*=":"])')

			if links:
				logger.info(f'📋 Found {len(links)} wiki links via CSS selector')

				# Pick the first link
				link_element = links[0]

				# Get link info using available methods
				basic_info = await link_element.get_basic_info()
				link_href = await link_element.get_attribute('href')

				logger.info(f'🎯 Selected element: <{basic_info["nodeName"]}>')
				logger.info(f'🔗 Link href: {link_href}')

				if basic_info['boundingBox']:
					bbox = basic_info['boundingBox']
					logger.info(f'📏 Position: ({bbox["x"]}, {bbox["y"]}) Size: {bbox["width"]}x{bbox["height"]}')

				# Test element interactions with robust implementations
				logger.info('👆 Hovering over the element...')
				await link_element.hover()
				await asyncio.sleep(1)

				logger.info('🔍 Focusing the element...')
				await link_element.focus()
				await asyncio.sleep(0.5)

				# Click the link using robust click method
				logger.info('🖱️ Clicking the link with robust fallbacks...')
				await link_element.click()

				# Wait for navigation
				await asyncio.sleep(3)

				# Get new page info
				new_url = await page.get_url()
				new_title = await page.get_title()
				logger.info(f'📄 Navigated to: {new_title}')
				logger.info(f'🌐 New URL: {new_url}')
			else:
				logger.warning('❌ No links found to interact with')

		except Exception as e:
			logger.warning(f'⚠️ Link interaction failed: {e}')

		# Scroll down the page
		logger.info('📜 Scrolling down the page...')
		mouse = await page.mouse
		await mouse.scroll(x=0, y=100, delta_y=500)
		await asyncio.sleep(1)

		# Test mouse operations
		logger.info('🖱️ Testing mouse operations...')
		await mouse.move(x=100, y=200)
		await mouse.click(x=150, y=250)

		# Execute more JavaScript examples
		logger.info('🧪 Testing JavaScript evaluation...')

		# Simple expressions
		page_height = await page.evaluate('() => document.body.scrollHeight')
		current_scroll = await page.evaluate('() => window.pageYOffset')
		logger.info(f'📏 Page height: {page_height}px, current scroll: {current_scroll}px')

		# JavaScript with arguments
		result = await page.evaluate('(x) => x * 2', 21)
		logger.info(f'🧮 JavaScript with args: 21 * 2 = {result}')

		# More complex JavaScript
		page_stats = json.loads(
			await page.evaluate("""() => {
			return {
				url: window.location.href,
				title: document.title,
				links: document.querySelectorAll('a').length,
				images: document.querySelectorAll('img').length,
				scrollTop: window.pageYOffset,
				viewportHeight: window.innerHeight
			};
		}""")
		)
		logger.info(f'📊 Page stats: {page_stats}')

		# Get page title using different methods
		title_via_js = await page.evaluate('() => document.title')
		title_via_api = await page.get_title()
		logger.info(f'📝 Title via JS: "{title_via_js}"')
		logger.info(f'📝 Title via API: "{title_via_api}"')

		# Take a final screenshot
		logger.info('📸 Taking final screenshot...')
		final_screenshot = await page.screenshot()
		logger.info(f'📸 Final screenshot: {len(final_screenshot)} bytes')

		# Test browser navigation with error handling
		logger.info('⬅️ Testing browser back navigation...')
		try:
			await page.go_back()
			await asyncio.sleep(2)

			back_url = await page.get_url()
			back_title = await page.get_title()
			logger.info(f'📄 After going back: {back_title}')
			logger.info(f'🌐 Back URL: {back_url}')
		except RuntimeError as e:
			logger.info(f'ℹ️ Navigation back failed as expected: {e}')

		# Test creating new page
		logger.info('🆕 Creating new blank page...')
		new_page = await browser.new_page()
		new_page_url = await new_page.get_url()
		logger.info(f'🆕 New page created with URL: {new_page_url}')

		# Get all pages
		all_pages = await browser.get_pages()
		logger.info(f'📑 Total pages: {len(all_pages)}')

		# Test form interaction if we can find a form
		try:
			# Look for search input on the page
			search_inputs = await page.get_elements_by_css_selector('input[type="search"], input[name*="search"]')

			if search_inputs:
				search_input = search_inputs[0]
				logger.info('🔍 Found search input, testing form interaction...')

				await search_input.focus()
				await search_input.fill('test search query')
				await page.press('Enter')

				logger.info('✅ Form interaction test completed')
			else:
				logger.info('ℹ️ No search inputs found for form testing')

		except Exception as e:
			logger.info(f'ℹ️ Form interaction test skipped: {e}')

			# wait 2 seconds before closing the new page
		logger.info('🕒 Waiting 2 seconds before closing the new page...')
		await asyncio.sleep(2)
		logger.info('🗑️ Closing new page...')
		await browser.close_page(new_page)

		logger.info('✅ Playground completed successfully!')

		input('Press Enter to continue...')

	except Exception as e:
		logger.error(f'❌ Error in playground: {e}', exc_info=True)

	finally:
		# Clean up
		logger.info('🧹 Cleaning up...')
		try:
			await browser.stop()
			logger.info('✅ Browser session stopped')
		except Exception as e:
			logger.error(f'❌ Error stopping browser: {e}')


if __name__ == '__main__':
	asyncio.run(main())
