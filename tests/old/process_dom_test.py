import asyncio
import json
import os
import time

import anyio

from browser_use.browser import BrowserProfile, BrowserSession


async def test_process_dom():
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await browser_session.start()
	try:
		page = await browser_session.get_current_page()
		await page.goto('https://kayak.com/flights')
		# await page.goto('https://google.com/flights')
		# await page.goto('https://immobilienscout24.de')
		# await page.goto('https://seleniumbase.io/w3schools/iframes')

		await asyncio.sleep(3)

		async with await anyio.open_file('browser_use/dom/buildDomTree.js', 'r') as f:
			js_code = await f.read()

		start = time.time()
		dom_tree = await page.evaluate(js_code)
		end = time.time()

		# print(dom_tree)
		print(f'Time: {end - start:.2f}s')

		os.makedirs('./tmp', exist_ok=True)
		async with await anyio.open_file('./tmp/dom.json', 'w') as f:
			await f.write(json.dumps(dom_tree, indent=1))

		# both of these work for immobilienscout24.de
		# await page.click('.sc-dcJsrY.ezjNCe')
		# await page.click(
		# 	'div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div > div > button:nth-of-type(2)'
		# )

		input('Press Enter to continue...')
	finally:
		await browser_session.stop()
