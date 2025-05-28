import asyncio
import os

import anyio
from langchain_openai import ChatOpenAI

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.dom.service import DomService


def count_string_tokens(string: str, model: str) -> tuple[int, float]:
	"""Count the number of tokens in a string using a specified model."""

	def get_price_per_token(model: str) -> float:
		"""Get the price per token for a specified model.

		@todo: move to utils, use a package or sth
		"""
		prices = {
			'gpt-4o': 2.5 / 1e6,
			'gpt-4o-mini': 0.15 / 1e6,
		}
		return prices[model]

	llm = ChatOpenAI(model=model)
	token_count = llm.get_num_tokens(string)
	price = token_count * get_price_per_token(model)
	return token_count, price


TIMEOUT = 60

DEFAULT_INCLUDE_ATTRIBUTES = [
	'id',
	'title',
	'type',
	'name',
	'role',
	'aria-label',
	'placeholder',
	'value',
	'alt',
	'aria-expanded',
	'data-date-format',
]


async def test_focus_vs_all_elements():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			# executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			disable_security=True,
			wait_for_network_idle_page_load_time=1,
			headless=True,
		)
	)

	websites = [
		'https://demos.telerik.com/kendo-react-ui/treeview/overview/basic/func?theme=default-ocean-blue-a11y',
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
		'https://google.com',
		'https://amazon.com',
		'https://github.com',
	]

	await browser_session.start()
	page = await browser_session.get_current_page()
	dom_service = DomService(page)

	for website in websites:
		# sleep 2
		await page.goto(website)
		asyncio.sleep(1)

		last_clicked_index = None  # Track the index for text input
		while True:
			try:
				print(f'\n{"=" * 50}\nTesting {website}\n{"=" * 50}')

				# Get/refresh the state (includes removing old highlights)
				print('\nGetting page state...')
				all_elements_state = await browser_session.get_state_summary(True)

				selector_map = all_elements_state.selector_map
				total_elements = len(selector_map.keys())
				print(f'Total number of elements: {total_elements}')

				# print(all_elements_state.element_tree.clickable_elements_to_string())
				prompt = AgentMessagePrompt(
					browser_state_summary=all_elements_state,
					result=None,
					include_attributes=DEFAULT_INCLUDE_ATTRIBUTES,
					step_info=None,
				)
				# print(prompt.get_user_message(use_vision=False).content)
				# Write the user message to a file for analysis
				user_message = prompt.get_user_message(use_vision=False).content
				os.makedirs('./tmp', exist_ok=True)
				async with await anyio.open_file('./tmp/user_message.txt', 'w', encoding='utf-8') as f:
					await f.write(user_message)

				token_count, price = count_string_tokens(user_message, model='gpt-4o')
				print(f'Prompt token count: {token_count}, price: {round(price, 4)} USD')
				print('User message written to ./tmp/user_message.txt')

				# also save all_elements_state.element_tree.clickable_elements_to_string() to a file
				# with open('./tmp/clickable_elements.json', 'w', encoding='utf-8') as f:
				# 	f.write(json.dumps(all_elements_state.element_tree.__json__(), indent=2))
				# print('Clickable elements written to ./tmp/clickable_elements.json')

				answer = input("Enter element index to click, 'index,text' to input, or 'q' to quit: ")

				if answer.lower() == 'q':
					break

				try:
					if ',' in answer:
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
							print(f"Invalid input: '{answer}'. Enter an index, 'index,text', or 'q'.")

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
