import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.types import Page
from browser_use.llm import ChatOpenAI

# Initialize controller
controller = Controller()

download_path = Path.cwd() / 'downloads'
download_path.mkdir(parents=True, exist_ok=True)


# Save PDF - exact copy from original controller function
@controller.registry.action('Save the current page as a PDF file')
async def save_pdf(page: Page):
	short_url = re.sub(r'^https?://(?:www\.)?|/$', '', page.url)
	slug = re.sub(r'[^a-zA-Z0-9]+', '-', short_url).strip('-').lower()
	sanitized_filename = f'{slug}.pdf'

	await page.emulate_media(media='screen')
	await page.pdf(path=download_path / sanitized_filename, format='A4', print_background=False)
	msg = f'Saving page with URL {page.url} as PDF to {download_path / sanitized_filename}'
	return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=f'Saved PDF to {sanitized_filename}')


async def main():
	"""
	Example task: Navigate to browser-use.com and save the page as a PDF
	"""
	task = """
	Go to https://browser-use.com/ and save the page as a PDF file.
	"""

	# Initialize the language model
	model = ChatOpenAI(model='gpt-4.1-mini')

	# Create and run the agent
	agent = Agent(task=task, llm=model, controller=controller)

	result = await agent.run()
	print(f'🎯 Task completed: {result}')


if __name__ == '__main__':
	asyncio.run(main())
