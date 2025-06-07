import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext


async def analyze_page_structure(url: str):
	"""Analyze and print the structure of a webpage with enhanced debugging"""
	browser = Browser(
		config=BrowserConfig(
			headless=False,  # Set to True if you don't need to see the browser
		),
		user_data_dir=None,
	)

	context = BrowserContext(browser=browser)

	try:
		async with context as ctx:
			# Navigate to the URL
			page = await ctx.get_current_page()
			await page.goto(url)
			await page.wait_for_load_state('networkidle')

			# Get viewport dimensions
			viewport_info = await page.evaluate("""() => {
				return {
					viewport: {
						width: window.innerWidth,
						height: window.innerHeight,
						scrollX: window.scrollX,
						scrollY: window.scrollY
					}
				}
			}""")

			print('\nViewport Information:')
			print(f'Width: {viewport_info["viewport"]["width"]}')
			print(f'Height: {viewport_info["viewport"]["height"]}')
			print(f'ScrollX: {viewport_info["viewport"]["scrollX"]}')
			print(f'ScrollY: {viewport_info["viewport"]["scrollY"]}')

			# Enhanced debug information for cookie consent and fixed position elements
			debug_info = await page.evaluate("""() => {
				function getElementInfo(element) {
					const rect = element.getBoundingClientRect();
					const style = window.getComputedStyle(element);
					return {
						tag: element.tagName.toLowerCase(),
						id: element.id,
						className: element.className,
						position: style.position,
						rect: {
							top: rect.top,
							right: rect.right,
							bottom: rect.bottom,
							left: rect.left,
							width: rect.width,
							height: rect.height
						},
						isFixed: style.position === 'fixed',
						isSticky: style.position === 'sticky',
						zIndex: style.zIndex,
						visibility: style.visibility,
						display: style.display,
						opacity: style.opacity
					};
				}

				// Find cookie-related elements
				const cookieElements = Array.from(document.querySelectorAll('[id*="cookie"], [id*="consent"], [class*="cookie"], [class*="consent"]'));
				const fixedElements = Array.from(document.querySelectorAll('*')).filter(el => {
					const style = window.getComputedStyle(el);
					return style.position === 'fixed' || style.position === 'sticky';
				});

				return {
					cookieElements: cookieElements.map(getElementInfo),
					fixedElements: fixedElements.map(getElementInfo)
				};
			}""")

			print('\nCookie-related Elements:')
			for elem in debug_info['cookieElements']:
				print(f'\nElement: {elem["tag"]}#{elem["id"]} .{elem["className"]}')
				print(f'Position: {elem["position"]}')
				print(f'Rect: {elem["rect"]}')
				print(f'Z-Index: {elem["zIndex"]}')
				print(f'Visibility: {elem["visibility"]}')
				print(f'Display: {elem["display"]}')
				print(f'Opacity: {elem["opacity"]}')

			print('\nFixed/Sticky Position Elements:')
			for elem in debug_info['fixedElements']:
				print(f'\nElement: {elem["tag"]}#{elem["id"]} .{elem["className"]}')
				print(f'Position: {elem["position"]}')
				print(f'Rect: {elem["rect"]}')
				print(f'Z-Index: {elem["zIndex"]}')

			print(f'\nPage Structure for {url}:\n')
			structure = await ctx.get_page_structure()
			print(structure)

			input('Press Enter to close the browser...')
	finally:
		await browser.close()


if __name__ == '__main__':
	# You can modify this URL to analyze different pages

	urls = [
		'https://www.mlb.com/yankees/stats/',
		'https://immobilienscout24.de',
		'https://www.zeiss.com/career/en/job-search.html?page=1',
		'https://www.zeiss.com/career/en/job-search.html?page=1',
		'https://reddit.com',
	]
	for url in urls:
		asyncio.run(analyze_page_structure(url))
