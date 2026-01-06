import asyncio

from pydantic import BaseModel

from browser_use import Browser, ChatOpenAI

TASK = """
On the current wikipedia page, find the latest huge edit and tell me what is was about.
"""


class LatestEditFinder(BaseModel):
	"""Find the latest huge edit on the current wikipedia page."""

	latest_edit: str
	edit_time: str
	edit_author: str
	edit_summary: str
	edit_url: str


llm = ChatOpenAI('gpt-4.1-mini')


async def main():
	"""
	Main function demonstrating mixed automation with Browser-Use and Playwright.
	"""
	print('🚀 Mixed Automation with Browser-Use and Actor API')

	browser = Browser(keep_alive=True)
	await browser.start()

	page = await browser.get_current_page() or await browser.new_page()

	# Go to apple wikipedia page
	await page.goto('https://browser-use.github.io/stress-tests/challenges/angularjs-form.html')

	await asyncio.sleep(1)

	element = await page.get_element_by_prompt('zip code input', llm)

	print('Element found', element)

	if element:
		await element.click()
	else:
		print('No element found')

	await browser.stop()


if __name__ == '__main__':
	asyncio.run(main())
