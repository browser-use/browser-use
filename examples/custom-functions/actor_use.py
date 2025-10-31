import asyncio
import os
import sys

from browser_use.browser.session import BrowserSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import ActionResult, Agent, ChatOpenAI, Tools

tools = Tools()

llm = ChatOpenAI(model='gpt-4.1-mini')


@tools.registry.action('Click on submit button')
async def click_submit_button(browser_session: BrowserSession):
	page = await browser_session.must_get_current_page()

	submit_button = await page.must_get_element_by_prompt('submit button', llm)
	await submit_button.click()

	return ActionResult(is_done=True, extracted_content='Submit button clicked!')


async def main():
	task = 'go to brower-use.com and then click on the submit button'
	agent = Agent(task=task, llm=llm, tools=tools)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
