import os
import sys

from browser_use.browser.context import BrowserContext

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

import pyperclip
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig

browser = Browser(
	config=BrowserConfig(
		browser_binary_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	),
)

# Load environment variables
load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


controller = Controller()


def is_google_sheet(page) -> bool:
	return page.url.startswith('https://docs.google.com/spreadsheets/')


@controller.registry.action('Google Sheets: Open a specific Google Sheet')
async def open_google_sheet(browser: BrowserContext, google_sheet_url: str):
	page = await browser.get_current_page()
	if page.url != google_sheet_url:
		await page.goto(google_sheet_url)
		await page.wait_for_load_state()
	if not is_google_sheet(page):
		return ActionResult(error='Failed to open Google Sheet, are you sure you have permissions to access this sheet?')
	return ActionResult(extracted_content=f'Opened Google Sheet {google_sheet_url}', include_in_memory=False)


@controller.registry.action('Google Sheets: Get the contents of the entire sheet', page_filter=is_google_sheet)
async def get_sheet_contents(browser: BrowserContext):
	page = await browser.get_current_page()

	# select all cells
	await page.keyboard.press('Enter')
	await page.keyboard.press('Escape')
	await page.keyboard.press('ControlOrMeta+A')
	await page.keyboard.press('ControlOrMeta+C')

	extracted_tsv = pyperclip.paste()
	return ActionResult(extracted_content=extracted_tsv, include_in_memory=True)


@controller.registry.action('Google Sheets: Select a specific cell or range of cells', page_filter=is_google_sheet)
async def select_cell_or_range(browser: BrowserContext, cell_or_range: str):
	page = await browser.get_current_page()

	await page.keyboard.press('Enter')  # make sure we dont delete current cell contents if we were last editing
	await page.keyboard.press('Escape')  # to clear current focus (otherwise select range popup is additive)
	await asyncio.sleep(0.1)
	await page.keyboard.press('Home')  # move cursor to the top left of the sheet first
	await page.keyboard.press('ArrowUp')
	await asyncio.sleep(0.1)
	await page.keyboard.press('Control+G')  # open the goto range popup
	await asyncio.sleep(0.2)
	await page.keyboard.type(cell_or_range, delay=0.05)
	await asyncio.sleep(0.2)
	await page.keyboard.press('Enter')
	await asyncio.sleep(0.2)
	await page.keyboard.press('Escape')  # to make sure the popup still closes in the case where the jump failed
	return ActionResult(extracted_content=f'Selected cell {cell_or_range}', include_in_memory=False)


@controller.registry.action('Google Sheets: Get the contents of a specific cell or range of cells', page_filter=is_google_sheet)
async def get_range_contents(browser: BrowserContext, cell_or_range: str):
	page = await browser.get_current_page()

	await select_cell_or_range(browser, cell_or_range)

	await page.keyboard.press('ControlOrMeta+C')
	await asyncio.sleep(0.1)
	extracted_tsv = pyperclip.paste()
	return ActionResult(extracted_content=extracted_tsv, include_in_memory=True)


@controller.registry.action('Google Sheets: Clear the currently selected cells', page_filter=is_google_sheet)
async def clear_selected_range(browser: BrowserContext):
	page = await browser.get_current_page()

	await page.keyboard.press('Backspace')
	return ActionResult(extracted_content='Cleared selected range', include_in_memory=False)


@controller.registry.action('Google Sheets: Input text into the currently selected cell', page_filter=is_google_sheet)
async def input_selected_cell_text(browser: BrowserContext, text: str):
	page = await browser.get_current_page()

	await page.keyboard.type(text, delay=0.1)
	await page.keyboard.press('Enter')  # make sure to commit the input so it doesn't get overwritten by the next action
	await page.keyboard.press('ArrowUp')
	return ActionResult(extracted_content=f'Inputted text {text}', include_in_memory=False)


@controller.registry.action('Google Sheets: Batch update a range of cells', page_filter=is_google_sheet)
async def update_range_contents(browser: BrowserContext, range: str, new_contents_tsv: str):
	page = await browser.get_current_page()

	await select_cell_or_range(browser, range)

	# simulate paste event from clipboard with TSV content
	await page.evaluate(f"""
		const clipboardData = new DataTransfer();
		clipboardData.setData('text/plain', `{new_contents_tsv}`);
		document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData}}));
	""")

	return ActionResult(extracted_content=f'Updated cell {range} with {new_contents_tsv}', include_in_memory=False)


# many more snippets for keyboard-shortcut based Google Sheets automation can be found here, see:
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/sheet_actions.js
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/commands.js
# - https://support.google.com/docs/answer/181110?hl=en&co=GENIE.Platform%3DDesktop#zippy=%2Cmac-shortcuts

# Tip: LLM is bad at spatial reasoning, don't make it navigate with arrow keys relative to current cell
# if given arrow keys, it will try to jump from G1 to A2 by pressing Down, without realizing needs to go Down+LeftLeftLeftLeft


async def main():
	async with await browser.new_context() as context:
		model = ChatOpenAI(model='gpt-4o')

		eraser = Agent(
			task="""
				Clear all the existing values in columns A through F in this Google Sheet:
				https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
			""",
			llm=model,
			browser_context=context,
			controller=controller,
		)
		await eraser.run()

		researcher = Agent(
			task="""
				Google to find the full name, nationality, and date of birth of the CEO of the top 10 Fortune 100 companies.
				For each company, append a row to this existing Google Sheet: https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
				Make sure column headers are present and all existing values in the sheet are formatted correctly.
				Columns:
					A: Company Name
					B: CEO Full Name
					C: CEO Country of Birth
					D: CEO Date of Birth (YYYY-MM-DD)
					E: Source URL where the information was found
			""",
			llm=model,
			browser_context=context,
			controller=controller,
		)
		await researcher.run()

		improvised_continuer = Agent(
			task="""
				Read the Google Sheet https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
				Add 3 more rows to the bottom continuing the existing pattern, make sure any data you add is sourced correctly.
			""",
			llm=model,
			browser_context=context,
			controller=controller,
		)
		await improvised_continuer.run()

		final_fact_checker = Agent(
			task="""
				Read the Google Sheet https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
				Fact-check every entry, add a new column F with your findings for each row.
				Make sure to check the source URL for each row, and make sure the information is correct.
			""",
			llm=model,
			browser_context=context,
			controller=controller,
		)
		await final_fact_checker.run()


if __name__ == '__main__':
	asyncio.run(main())
