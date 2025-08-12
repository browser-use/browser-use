import asyncio
import json
import time

import aiofiles

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.types import ViewportSize
from browser_use.dom.debug.highlights import inject_highlighting_script, remove_highlighting_script
from browser_use.dom.service import DomService
from browser_use.dom.views import EnhancedDOMTreeNode


async def main():
	# async with async_playwright() as p:
	# 	playwright_browser = await p.chromium.launch(args=['--remote-debugging-port=9222'], headless=False)
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			# executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			window_size=ViewportSize(width=1100, height=1000),
			disable_security=True,
			wait_for_network_idle_page_load_time=1,
			headless=False,
			args=['--incognito'],
		),
	)
	# async with httpx.AsyncClient() as client:
	# 	version_info = await client.get('http://localhost:9222/json/version')
	# 	browser.cdp_url = version_info.json()['webSocketDebuggerUrl']

	# if not browser.cdp_url:
	# 	raise ValueError('CDP URL is not set')  # can't happen in this case actually

	# await browser.create_new_tab('https://en.wikipedia.org/wiki/Apple_Inc.')
	# await browser.create_new_tab('https://semantic-ui.com/modules/dropdown.html#/definition')
	# await browser.navigate('https://v0-website-with-clickable-elements.vercel.app/iframe-buttons')
	from browser_use.browser.events import NavigateToUrlEvent

	nav_event = browser.event_bus.dispatch(
		NavigateToUrlEvent(url='https://v0-website-with-clickable-elements.vercel.app/nested-iframe')
	)
	await nav_event

	# Wait a moment for page to fully load
	await asyncio.sleep(2)

	while True:
		async with DomService(browser) as dom_service:
			await remove_highlighting_script(dom_service)

			start = time.time()
			# Get current target ID from browser session
			if browser.agent_focus and browser.agent_focus.target_id:
				target_id = browser.agent_focus.target_id
			else:
				# Get first available target
				targets = await browser._cdp_get_all_pages()
				if not targets:
					raise ValueError('No targets available')
				target_id = targets[0]['targetId']

			result = await dom_service.get_dom_tree(target_id)
			if isinstance(result, tuple):
				dom_tree = result[0]
				dom_timing = result[1] if len(result) > 1 else {}
			else:
				dom_tree = result
				dom_timing = {}

			end = time.time()
			print(f'Time taken: {end - start} seconds')

			async with aiofiles.open('tmp/enhanced_dom_tree.json', 'w') as f:
				await f.write(json.dumps(dom_tree.__json__(), indent=1))

			print('Saved enhanced dom tree to tmp/enhanced_dom_tree.json')

			# Print some sample information about visible/clickable elements
			visible_clickable_count = 0
			total_with_snapshot = 0

			def count_elements(node: EnhancedDOMTreeNode):
				nonlocal visible_clickable_count, total_with_snapshot
				if node.snapshot_node:
					total_with_snapshot += 1
					if node.is_visible and node.snapshot_node.is_clickable:
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

			start = time.time()
			snapshot, dom_tree, ax_tree, _ = await dom_service._get_all_trees()
			end = time.time()
			print(f'Time taken: {end - start} seconds')

			async with aiofiles.open('tmp/snapshot.json', 'w') as f:
				await f.write(json.dumps(snapshot, indent=1))

			async with aiofiles.open('tmp/dom_tree.json', 'w') as f:
				await f.write(json.dumps(dom_tree, indent=1))

			async with aiofiles.open('tmp/ax_tree.json', 'w') as f:
				await f.write(json.dumps(ax_tree, indent=1))

			print('saved dom tree to tmp/dom_tree.json')
			print('saved snapshot to tmp/snapshot.json')
			print('saved ax tree to tmp/ax_tree.json')

			await inject_highlighting_script(dom_service, serialized_dom_state.selector_map)

			input('Done. Press Enter to continue...')


if __name__ == '__main__':
	asyncio.run(main())
