import asyncio
import json
import os
import time

import anyio
import pyperclip
import tiktoken

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.types import ViewportSize
from browser_use.dom.service import DomService
from browser_use.dom.views import DEFAULT_INCLUDE_ATTRIBUTES
from browser_use.filesystem.file_system import FileSystem

TIMEOUT = 60


async def test_focus_vs_all_elements():
	# async with async_patchright() as patchright:
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			# executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			window_size=ViewportSize(width=1100, height=1000),
			disable_security=True,
			wait_for_network_idle_page_load_time=1,
			headless=False,
		),
		# playwright=patchright,
	)

	websites = [
		# 'https://demos.telerik.com/kendo-react-ui/treeview/overview/basic/func?theme=default-ocean-blue-a11y',
		'https://google.com',
		'https://www.ycombinator.com/companies',
		'https://kayak.com/flights',
		# 'https://en.wikipedia.org/wiki/Humanist_Party_of_Ontario',
		# 'https://www.google.com/travel/flights?tfs=CBwQARoJagcIARIDTEpVGglyBwgBEgNMSlVAAUgBcAGCAQsI____________AZgBAQ&tfu=KgIIAw&hl=en-US&gl=US',
		# # 'https://www.concur.com/?&cookie_preferences=cpra',
		# 'https://immobilienscout24.de',
		'https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit',
		'https://www.zeiss.com/career/en/job-search.html?page=1',
		'https://www.mlb.com/yankees/stats/',
		'https://www.amazon.com/s?k=laptop&s=review-rank&crid=1RZCEJ289EUSI&qid=1740202453&sprefix=laptop%2Caps%2C166&ref=sr_st_review-rank&ds=v1%3A4EnYKXVQA7DIE41qCvRZoNB4qN92Jlztd3BPsTFXmxU',
		'https://reddit.com',
		'https://codepen.io/geheimschriftstift/pen/mPLvQz',
		'https://www.google.com/search?q=google+hi&oq=google+hi&gs_lcrp=EgZjaHJvbWUyBggAEEUYOTIGCAEQRRhA0gEIMjI2NmowajSoAgCwAgE&sourceid=chrome&ie=UTF-8',
		'https://amazon.com',
		'https://github.com',
	]

	await browser_session.start()
	page = await browser_session.get_current_page()
	dom_service = DomService(page)

	for website in websites:
		# sleep 2
		await page.goto(website)
		await asyncio.sleep(1)

		last_clicked_index = None  # Track the index for text input
		while True:
			try:
				print(f'\n{"=" * 50}\nTesting {website}\n{"=" * 50}')

				# Get/refresh the state (includes removing old highlights)
				print('\nGetting page state...')

				start_time = time.time()
				all_elements_state = await browser_session.get_state_summary(True)
				end_time = time.time()
				print(f'get_state_summary took {end_time - start_time:.2f} seconds')

				selector_map = all_elements_state.selector_map
				total_elements = len(selector_map.keys())
				print(f'Total number of elements: {total_elements}')

				# print(all_elements_state.element_tree.clickable_elements_to_string())
				prompt = AgentMessagePrompt(
					browser_state_summary=all_elements_state,
					file_system=FileSystem(base_dir='./tmp'),
					include_attributes=DEFAULT_INCLUDE_ATTRIBUTES,
					step_info=None,
				)
				# Write the user message to a file for analysis
				user_message = prompt.get_user_message(use_vision=False).text

				# clickable_elements_str = all_elements_state.element_tree.clickable_elements_to_string()

				text_to_save = user_message

				os.makedirs('./tmp', exist_ok=True)
				async with await anyio.open_file('./tmp/user_message.txt', 'w', encoding='utf-8') as f:
					await f.write(text_to_save)

				# save pure clickable elements to a file
				async with await anyio.open_file('./tmp/element_tree.json', 'w', encoding='utf-8') as f:
					await f.write(json.dumps(all_elements_state.element_tree.__json__(), indent=0))

				# copy the user message to the clipboard
				# pyperclip.copy(text_to_save)

				encoding = tiktoken.encoding_for_model('gpt-4o')
				token_count = len(encoding.encode(text_to_save))
				print(f'Token count: {token_count}')

				print('User message written to ./tmp/user_message.txt')
				print('Element tree written to ./tmp/element_tree.json')

				# also save all_elements_state.element_tree.clickable_elements_to_string() to a file
				# with open('./tmp/clickable_elements.json', 'w', encoding='utf-8') as f:
				# 	f.write(json.dumps(all_elements_state.element_tree.__json__(), indent=2))
				# print('Clickable elements written to ./tmp/clickable_elements.json')

				answer = input(
					"Enter element index to click, 'index,text' to input, 'c,index' to copy element JSON, or 'q' to quit: "
				)

				if answer.lower() == 'q':
					break

				try:
					if answer.lower().startswith('c,'):
						# Copy element JSON format: c,index
						parts = answer.split(',', 1)
						if len(parts) == 2:
							try:
								target_index = int(parts[1].strip())
								if target_index in selector_map:
									element_node = selector_map[target_index]
									element_json = json.dumps(element_node.__json__(), indent=2, default=str)
									pyperclip.copy(element_json)
									print(f'Copied element {target_index} JSON to clipboard: {element_node.tag_name}')
								else:
									print(f'Invalid index: {target_index}')
							except ValueError:
								print(f'Invalid index format: {parts[1]}')
						else:
							print("Invalid input format. Use 'c,index'.")
					elif ',' in answer:
						# Input text format: index,text
						parts = answer.split(',', 1)
						if len(parts) == 2:
							try:
								target_index = int(parts[0].strip())
								text_to_input = parts[1]
								if target_index in selector_map:
									element_node = selector_map[target_index]
									print(
										f"Inputting text '{text_to_input}' into element {target_index}: {element_node.tag_name}"
									)
									await browser_session._input_text_element_node(element_node, text_to_input)
									print('Input successful.')
								else:
									print(f'Invalid index: {target_index}')
							except ValueError:
								print(f'Invalid index format: {parts[0]}')
						else:
							print("Invalid input format. Use 'index,text'.")
					else:
						# Click element format: index
						try:
							clicked_index = int(answer)
							if clicked_index in selector_map:
								element_node = selector_map[clicked_index]
								print(f'Clicking element {clicked_index}: {element_node.tag_name}')
								await browser_session._click_element_node(element_node)
								print('Click successful.')
							else:
								print(f'Invalid index: {clicked_index}')
						except ValueError:
							print(f"Invalid input: '{answer}'. Enter an index, 'index,text', 'c,index', or 'q'.")

				except Exception as action_e:
					print(f'Action failed: {action_e}')

			# No explicit highlight removal here, get_state handles it at the start of the loop

			except Exception as e:
				print(f'Error in loop: {e}')
				# Optionally add a small delay before retrying
				await asyncio.sleep(1)


if __name__ == '__main__':
	asyncio.run(test_focus_vs_all_elements())
	# asyncio.run(test_process_html_file()) # Commented out the other test
