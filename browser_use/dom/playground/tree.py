import asyncio
import json
import time

import aiofiles

from browser_use.browser import BrowserSession
from browser_use.dom.service import DomService


async def main():
	# async with async_playwright() as p:
	# 	playwright_browser = await p.chromium.launch(args=['--remote-debugging-port=9222'], headless=False)
	browser = BrowserSession()

	# async with httpx.AsyncClient() as client:
	# 	version_info = await client.get('http://localhost:9222/json/version')
	# 	browser.cdp_url = version_info.json()['webSocketDebuggerUrl']

	# if not browser.cdp_url:
	# 	raise ValueError('CDP URL is not set')  # can't happen in this case actually

	# await browser.create_new_tab('https://en.wikipedia.org/wiki/Apple_Inc.')
	# await browser.create_new_tab('https://semantic-ui.com/modules/dropdown.html#/definition')
	await browser.create_new_tab('https://select2.org/data-sources/ajax')
	await browser._wait_for_page_and_frames_load()

	dom_service = DomService(browser)

	while True:
		start = time.time()
		dom_tree, dom_timing = await dom_service.get_dom_tree()
		end = time.time()
		print(f'Time taken: {end - start} seconds')

		async with aiofiles.open('tmp/enhanced_dom_tree.json', 'w') as f:
			await f.write(json.dumps(dom_tree.__json__(), indent=1))

		print('Saved enhanced dom tree to tmp/enhanced_dom_tree.json')

		# Print some sample information about visible/clickable elements
		visible_clickable_count = 0
		total_with_snapshot = 0

		def count_elements(node):
			nonlocal visible_clickable_count, total_with_snapshot
			if node.snapshot_node:
				total_with_snapshot += 1
				if node.snapshot_node.is_visible and node.snapshot_node.is_clickable:
					visible_clickable_count += 1
					# print(f'Visible clickable element: {node.node_name} (cursor: {node.snapshot_node.cursor_style})')

			if node.children_nodes:
				for child in node.children_nodes:
					count_elements(child)

		count_elements(dom_tree)
		print(
			f'Found {visible_clickable_count} visible clickable elements out of {total_with_snapshot} elements with snapshot data'
		)

		serialized_dom_state, timing_info = await dom_service.get_serialized_dom_tree()

		async with aiofiles.open('tmp/serialized_dom_tree.txt', 'w') as f:
			await f.write(serialized_dom_state.llm_representation())

		# print(serialized)
		print('Saved serialized dom tree to tmp/serialized_dom_tree.txt')

		# print(selector_map)

		# start = time.time()
		# snapshot, dom_tree, ax_tree = await dom_service._get_all_trees()
		# end = time.time()
		# print(f'Time taken: {end - start} seconds')

		# async with aiofiles.open('tmp/snapshot.json', 'w') as f:
		# 	await f.write(json.dumps(snapshot, indent=1))

		# async with aiofiles.open('tmp/dom_tree.json', 'w') as f:
		# 	await f.write(json.dumps(dom_tree, indent=1))

		# async with aiofiles.open('tmp/ax_tree.json', 'w') as f:
		# 	await f.write(json.dumps(ax_tree, indent=1))

		# print('saved dom tree to tmp/dom_tree.json')
		# print('saved snapshot to tmp/snapshot.json')
		# print('saved ax tree to tmp/ax_tree.json')

		input('Done. Press Enter to continue...')


if __name__ == '__main__':
	asyncio.run(main())
