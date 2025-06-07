import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller
from browser_use.browser import BrowserProfile, BrowserSession

# Load environment variables
load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')

# Use the default controller with built-in Google Sheets actions
# The controller already includes all the necessary Google Sheets actions:
# - select_cell_or_range: Select specific cells or ranges (Ctrl+G navigation)
# - get_range_contents: Get contents of cells using clipboard
# - get_sheet_contents: Get entire sheet contents
# - clear_selected_range: Clear selected cells
# - input_selected_cell_text: Input text into selected cells
# - update_range_contents: Batch update ranges with TSV data
controller = Controller()

# For more Google Sheets keyboard shortcuts and automation ideas, see:
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/sheet_actions.js
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/commands.js
# - https://support.google.com/docs/answer/181110?hl=en&co=GENIE.Platform%3DDesktop#zippy=%2Cmac-shortcuts

# Tip: LLM is bad at spatial reasoning, don't make it navigate with arrow keys relative to current cell
# if given arrow keys, it will try to jump from G1 to A2 by pressing Down, without realizing needs to go Down+LeftLeftLeftLeft


async def main():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			user_data_dir='~/.config/browseruse/profiles/default',
		),
		keep_alive=True,
	)

	async with browser_session:
		model = ChatOpenAI(model='gpt-4o')

		# eraser = Agent(
		# 	task="""
		#         Clear all the existing values in columns A through M in this Google Sheet:
		#         https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
		#     """,
		# 	llm=model,
		# 	browser_session=browser_session,
		# 	controller=controller,
		# )
		# await eraser.run()

		researcher = Agent(
			task="""
				Open this Google Sheet and read it to understand the structure: https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
                Make sure column headers are present and all existing values in the sheet are formatted correctly.
                Columns should be labeled using the top row of cells:
                    A: "Company Name"
                    B: "CEO Full Name"
                    C: "CEO Country of Birth"
                    D: "Source URL where the information was found"
                Then Google to find the full name and nationality of each CEO of the top Fortune 100 companies and for each company,
                append a row to this existing Google Sheet. You can do a few searches at a time,
                but make sure to check the sheet for errors after inserting a new batch of rows.
                At the end, double check the formatting and structure and fix any issues by updating/overwriting cells.
            """,
			llm=model,
			browser_session=browser_session,
			controller=controller,
		)
		await researcher.run()

		# improvised_continuer = Agent(
		# 	task="""
		#         Read the Google Sheet https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
		#         Add 3 more rows to the bottom continuing the existing pattern, make sure any data you add is sourced correctly.
		#     """,
		# 	llm=model,
		# 	browser_session=browser_session,
		# 	controller=controller,
		# )
		# await improvised_continuer.run()

		# final_fact_checker = Agent(
		# 	task="""
		#         Read the Google Sheet https://docs.google.com/spreadsheets/d/1INaIcfpYXlMRWO__de61SHFCaqt1lfHlcvtXZPItlpI/edit
		#         Fact-check every entry, add a new column F with your findings for each row.
		#         Make sure to check the source URL for each row, and make sure the information is correct.
		#     """,
		# 	llm=model,
		# 	browser_session=browser_session,
		# 	controller=controller,
		# )
		# await final_fact_checker.run()


if __name__ == '__main__':
	asyncio.run(main())
