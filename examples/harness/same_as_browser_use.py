"""The harness agent used exactly like browser_use.

Every block below is valid against BOTH packages -- swap the import line and
the same code runs on browser-use's own engine or on Browser Harness (your
real Chrome, over the harness daemon).

    from browser_use import Agent, Browser, Tools, ChatOpenAI            # browser-use
    from browser_use.harness import Agent, Browser, Tools, ChatOpenAI    # harness
"""

import asyncio

from pydantic import BaseModel

from browser_use.harness import Agent, Browser, ChatBrowserUse, Tools


# 1. the one-liner -- identical to examples/simple.py
def simple():
	agent = Agent(task='Find the number of stars of the browser-use repo', llm=ChatBrowserUse())
	history = agent.run_sync()
	print(history.final_result())


# 2. custom tools -- same @tools.action decorator, same injected params
tools = Tools()


@tools.action('Read the main headline of the current page')
async def page_headline(browser: Browser) -> str:
	return str(await browser.js("document.querySelector('h1')?.innerText ?? ''"))


# 3. structured output -- same output_model_schema -> history.structured_output
class Repo(BaseModel):
	name: str
	stars: int


async def structured():
	agent = Agent(
		task='Get the star count of browser-use/browser-use',
		llm=ChatBrowserUse(),
		browser=Browser(),
		tools=tools,
		output_model_schema=Repo,
	)
	history = await agent.run(max_steps=20)
	print(history.structured_output)


# 4. browser primitives -- browser_use.BrowserSession names work as aliases
async def primitives():
	browser = Browser()
	await browser.start()
	await browser.navigate_to('https://example.com')
	print(await browser.get_current_page_url())
	print(await browser.get_current_page_title())
	print(len(await browser.get_tabs()))
	await browser.take_screenshot('shot.png')
	await browser.close()


# 5. deterministic tool calls, no LLM -- same as browser_use.Tools
async def deterministic():
	browser = Browser()
	await browser.start()
	await tools.navigate(url='https://example.com', browser=browser)
	result = await tools.search_page(pattern=r'Example \w+', regex=True, browser=browser)
	print(result.extracted_content)


# 6. hooks, pause/resume/stop, follow-up tasks -- same control surface
async def control():
	agent = Agent(task='Open example.com', llm=ChatBrowserUse())

	async def on_step_end(a: Agent) -> None:
		print(f'step {a.history.number_of_steps()} done')

	task = asyncio.create_task(agent.run(max_steps=10, on_step_end=on_step_end))
	await asyncio.sleep(5)
	agent.pause()
	agent.resume()
	history = await task
	agent.add_new_task('Now find the "More information" link')
	print(history.final_result())


if __name__ == '__main__':
	asyncio.run(primitives())
