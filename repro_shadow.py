import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from browser_use import Browser, BrowserConfig

load_dotenv()


async def main():
	file_path = Path(os.getcwd()) / 'repro_shadow.html'
	url = f'file:///{file_path}'

	# We need a real LLM to make the decision to click
	# Assuming user has provided API key or we can use a mock/fake LLM if needed.
	# For now, I'll use ChatOpenAI and hope env var is set, or user sets it.
	# If not, I might fail.
	# Actually, I can use a mock LLM that always outputs the action to click index X.
	# But I don't know the index yet.

	browser = Browser(config=BrowserConfig(headless=False))

	# Simple task
	task = "Click the 'Shadow Button'."

	# Use standard Agent
	# If API key missing, this will fail.
	# But I can use the same trick as before: manual inspection context.

	async with await browser.new_context() as context:
		page = await context.get_current_page()
		await page.goto(url)
		await asyncio.sleep(1)

		state = await context.get_state()

		print('\n--- Detected Elements ---')
		shadow_btn_idx = None
		for idx, el in state.selector_map.items():
			text = el.get_meaningful_text_for_llm()
			print(f'[{idx}] <{el.tag_name}> {text}')
			if 'Shadow Button' in text:
				shadow_btn_idx = idx

		if shadow_btn_idx is not None:
			print(f'\nAttempting to click element {shadow_btn_idx}...')
			# Simulate agent action
			# We don't have Agent instance here easily exposed to run ONE action.
			# But we can assume if the element is in selector_map, the agent *sees* it.
			# The issue might be that the *action execution* fails.

			# Let's try to verify if `xpath` or `selector` generated is valid for Shadow DOM.
			el = state.selector_map[shadow_btn_idx]
			print(f'XPath: {el.xpath}')
			print(f'Attributes: {el.attributes}')

			# The issue 3813 says "unable to click".
			# This usually means the selector generated doesn't work with playwright click,
			# OR the element is considered hidden.
		else:
			print('\nFAIL: Shadow Button not detected in selector map!')

	await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
