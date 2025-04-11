import json
import os
import time

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig


async def test_process_dom():
	browser = Browser(config=BrowserConfig(headless=False))

	async with await browser.new_context() as context:
		page = await context.get_current_page()
		await page.goto('https://kayak.com/flights')
		# await page.goto('https://google.com/flights')
		# await page.goto('https://immobilienscout24.de')
		# await page.goto('https://seleniumbase.io/w3schools/iframes')

		time.sleep(3)

		with open('browser_use/dom/buildDomTree.js', 'r') as f:
			js_code = f.read()

		start = time.time()
		dom_tree = await page.evaluate(js_code)
		end = time.time()

		# print(dom_tree)
		print(f'Time: {end - start:.2f}s')

		os.makedirs('./tmp', exist_ok=True)
		with open('./tmp/dom.json', 'w') as f:
			json.dump(dom_tree, f, indent=1)

		# both of these work for immobilienscout24.de
		# await page.click('.sc-dcJsrY.ezjNCe')
		# await page.click(
		# 	'div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div > div > button:nth-of-type(2)'
		# )

		input('Press Enter to continue...')


async def test_viewport_expansion_parameter():
	browser = Browser(config=BrowserConfig(headless=False))

	# Test only the two most important values for comparison:
	# -1: No viewport filtering - includes all elements on the page (maximum coverage)
	# 0: Strict viewport filtering - only includes elements visible in the current viewport (minimum coverage)
	viewport_values = [-1, 0]
	results = {}

	for value in viewport_values:
		browser_context_config = BrowserContextConfig(viewport_expansion=value)

		async with BrowserContext(browser=browser, config=browser_context_config) as context:
			page = await context.get_current_page()

			# go to page which has a lot of scrollable content
			await page.goto('https://www.fh-muenster.de/de/master-studiengaenge?filter={%22degrees%22:[4,5,6,7,8,9,10,11]}')
			await page.wait_for_load_state('networkidle')

			with open('browser_use/dom/buildDomTree.js', 'r') as f:
				js_code = f.read()

			dom_tree = await page.evaluate(js_code, {'viewportExpansion': value, 'debugMode': True})
			results[value] = {'total_elements': len(dom_tree['map'])}

	elements_all = results[-1]['total_elements']
	elements_viewport = results[0]['total_elements']
	reduction_percent = (elements_all - elements_viewport) / elements_all * 100

	print(f'Elements with no filtering (-1): {elements_all}')
	print(f'Elements in viewport only (0): {elements_viewport}')
	print(f'Reduction: {reduction_percent:.1f}%')

	assert elements_viewport < elements_all, 'Viewport expansion parameter is not working correctly'

	await browser.close()
	return elements_all, elements_viewport, reduction_percent


if __name__ == '__main__':
	import asyncio

	asyncio.run(test_viewport_expansion_parameter())
