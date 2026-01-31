"""
Test for Paris MOU ExtJS combobox interaction.

This test demonstrates the correct interaction pattern for ExtJS comboboxes:
1. Type into the combobox to trigger dropdown
2. Wait for dropdown to appear
3. Get fresh DOM state (dropdown items now visible)
4. Click on the matching dropdown option

The Paris MOU inspection search uses an ExtJS-based form inside a cross-origin
iframe from portal.emsa.europa.eu. browser-use handles this correctly with
cross_origin_iframes=True (default).

Usage:
    python paris_mou.py              # Manual interaction mode
    python paris_mou.py --simple      # Agent mode with task prompt
"""

import argparse
import asyncio
import sys

sys.stdout.reconfigure(line_buffering=True)


async def main_simple():
	"""Simple mode: Use Agent with task prompt"""
	from browser_use import Agent, Browser, ChatGoogle
	from browser_use.browser.profile import BrowserProfile
	from dotenv import load_dotenv

	load_dotenv()

	browser = Browser(
		browser_profile=BrowserProfile(
			headless=False,
			chromium_sandbox=False,
			cross_origin_iframes=True,
		)
	)
	print(f"DEBUG: cross_origin_iframes = {browser.browser_profile.cross_origin_iframes}")

	task = """can you please go use the web browser tool for me and go to the website Paris MOU. On this website, you have to look for the database search and you have to search for a ship with the name Destiny. Once you find it, I want you I want you to extract information - if there were any issues with this ship, please let me know."""

	agent = Agent(
		task=task,
		llm=ChatGoogle(model="gemini-flash-latest"),
		browser=browser,
	)

	print('Running agent with task...')
	await agent.run()


async def main():
	from browser_use import BrowserSession
	from browser_use.browser.events import ClickElementEvent, TypeTextEvent
	from browser_use.browser.profile import BrowserProfile

	browser = BrowserSession(
		browser_profile=BrowserProfile(
			headless=False,
			chromium_sandbox=False,
			cross_origin_iframes=True,
		)
	)
	await browser.start()

	page = await browser.get_current_page()
	await page.goto('https://parismou.org/inspection-Database/inspection-search')
	print('Waiting 12s for ExtJS to load...')
	await asyncio.sleep(12)

	state = await browser.get_browser_state_summary(include_screenshot=False)
	print(f'Initial DOM: {len(state.dom_state.selector_map)} elements')

	# Step 1: Type into shipName combobox
	ship_node = None
	for idx, node in state.dom_state.selector_map.items():
		if (node.attributes or {}).get('name') == 'shipName':
			ship_node = node
			print(f"Found shipName at index {idx}, typing 'Destiny'...")
			await browser.event_bus.dispatch(TypeTextEvent(node=node, text='Destiny', clear=True, is_sensitive=False))
			break

	if not ship_node:
		print('ERROR: shipName field not found!')
		await browser.close()
		return

	# Step 2: Wait for dropdown to appear
	print('Waiting 2s for dropdown...')
	await asyncio.sleep(2)

	# Step 3: Get fresh DOM state with dropdown items
	state2 = await browser.get_browser_state_summary(include_screenshot=False)
	print(f'After typing: {len(state2.dom_state.selector_map)} elements')

	# Step 4: Find and click the DESTINY option
	destiny_node = None
	for idx, node in state2.dom_state.selector_map.items():
		ax_name = node.ax_node.name if node.ax_node else ''
		if ax_name == 'DESTINY':
			destiny_node = node
			print(f"Found 'DESTINY' at index {idx}, position: {node.absolute_position}")
			break

	if destiny_node:
		print('Clicking DESTINY option...')
		await browser.event_bus.dispatch(ClickElementEvent(node=destiny_node))
		print('Clicked!')
		await asyncio.sleep(2)
	else:
		print('ERROR: DESTINY option not found in dropdown!')

	# Keep browser open briefly to observe result
	print('Check browser to verify selection worked.')
	await asyncio.sleep(5)
	await browser.close()
	print('Done!')


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Paris MOU ExtJS combobox test')
	parser.add_argument(
		'--simple',
		action='store_true',
		help='Use Agent with task prompt instead of manual interaction',
	)
	args = parser.parse_args()

	if args.simple:
		asyncio.run(main_simple())
	else:
		asyncio.run(main())
