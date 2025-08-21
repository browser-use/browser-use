import asyncio
import json

import anyio

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import ClickElementEvent
from browser_use.dom.views import DOMBaseNode, DOMElementNode, DOMTextNode
from browser_use.utils import time_execution_sync


class ElementTreeSerializer:
	@staticmethod
	def dom_element_node_to_json(element_tree: DOMElementNode) -> dict:
		def node_to_dict(node: DOMBaseNode) -> dict:
			if isinstance(node, DOMTextNode):
				return {'type': 'text', 'text': node.text}
			elif isinstance(node, DOMElementNode):
				return {
					'type': 'element',
					'tag_name': node.tag_name,
					'attributes': node.attributes,
					'highlight_index': node.highlight_index,
					'children': [node_to_dict(child) for child in node.children],
				}
			return {}

		return node_to_dict(element_tree)


# run with: pytest browser_use/browser/tests/test_clicks.py
async def test_highlight_elements():
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await browser_session.start()
	try:
		page = await browser_session.get_current_page()
		# await page.goto('https://immobilienscout24.de')
		# await page.goto('https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/service-plans')
		# await page.goto('https://google.com/search?q=elon+musk')
		# await page.goto('https://kayak.com')
		# await page.goto('https://www.w3schools.com/tags/tryit.asp?filename=tryhtml_iframe')
		# await page.goto('https://dictionary.cambridge.org')
		# await page.goto('https://github.com')
		await page.goto('https://huggingface.co/')

		await asyncio.sleep(1)

		while True:
			try:
				# await asyncio.sleep(10)
				state = await browser_session.get_state_summary(cache_clickable_elements_hashes=True)

				async with await anyio.open_file('./tmp/page.json', 'w') as f:
					await f.write(
						json.dumps(
							ElementTreeSerializer.dom_element_node_to_json(state.element_tree),
							indent=1,
						)
					)

				# await time_execution_sync('highlight_selector_map_elements')(
				# 	browser.highlight_selector_map_elements
				# )(state.selector_map)

				# Find and print duplicate XPaths
				xpath_counts = {}
				if not state.selector_map:
					continue
				for selector in state.selector_map.values():
					xpath = selector.xpath
					if xpath in xpath_counts:
						xpath_counts[xpath] += 1
					else:
						xpath_counts[xpath] = 1

				print('\nDuplicate XPaths found:')
				for xpath, count in xpath_counts.items():
					if count > 1:
						print(f'XPath: {xpath}')
						print(f'Count: {count}\n')

				print(list(state.selector_map.keys()), 'Selector map keys')
				print(state.element_tree.clickable_elements_to_string())
				action = input('Select next action: ')

				await time_execution_sync('remove_highlight_elements')(browser_session.remove_highlights)()

				node_element = state.selector_map[int(action)]

				# check if index of selector map are the same as index of items in dom_items

				event = browser_session.event_bus.dispatch(ClickElementEvent(element_node=node_element))
				await event

			except Exception as e:
				print(e)
	finally:
		await browser_session.stop()
