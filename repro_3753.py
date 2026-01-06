import asyncio
import os
from pathlib import Path

from browser_use import Browser, BrowserConfig


async def main():
	# Get absolute path to the HTML file
	file_path = Path(os.getcwd()) / 'repro_3753.html'
	url = f'file:///{file_path}'

	print(f'Opening {url}')

	browser = Browser(config=BrowserConfig(headless=False))

	# We will just open the browser and basic agent to see the initial inspection
	# We can't easily assert visual output here without a vision model,
	# but we can inspect the DOM tree the agent sees.

	task = 'Look at the buttons on the page. Which ones are interactive?'

	# Mock LLM to avoid API key needed, we just want to run the browser step
	# But Agent requires LLM. We can reuse the ChatOpenAI or...
	# Actually, we can use BrowserSession directly to get the DOM state.

	async with await browser.new_context() as context:
		page = await context.get_current_page()
		await page.goto(url)

		# Give it a moment
		await asyncio.sleep(2)

		# Get the DOM state that `browser-use` extracts
		# We need to access the internal extraction logic.
		# BrowserContext.get_state() -> returns BrowserState

		state = await context.get_state()

		# Check which elements are in the selector map (interactive)
		print('\n--- Interactive Elements Detected ---')
		for index, element in state.selector_map.items():
			print(f'ID {index}: <{element.tag_name}> - {element.get_meaningful_text_for_llm()}')
			if hasattr(element, 'attributes'):
				print(f'   Attrs: {element.attributes}')

		print('\n--- Checking specific targets ---')
		found_span = any('Ant Design Span Button' in e.get_meaningful_text_for_llm() for e in state.selector_map.values())
		found_label = any('Clickable Label' in e.get_meaningful_text_for_llm() for e in state.selector_map.values())

		print(f'Span Button Detected: {found_span}')
		print(f'Label Button Detected: {found_label}')

	await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
