"""Structured output + custom tools + deterministic scripting with the harness agent.

Shows the three layers:
1. deterministic Browser calls (no LLM),
2. a custom @tools.action,
3. output_model_schema -> typed history.structured_output.
"""

import asyncio

from pydantic import BaseModel

from browser_use import ChatBrowserUse
from browser_use.harness import Agent, Browser, Tools


class Repo(BaseModel):
	name: str
	stars: int


class Repos(BaseModel):
	repos: list[Repo]


tools = Tools()


@tools.action('Read the README headline of the current repository page')
async def readme_headline(browser: Browser) -> str:
	return str(await browser.js("document.querySelector('article h1')?.innerText ?? ''"))


async def main():
	browser = Browser()  # attaches to your real Chrome via the harness daemon

	# Layer 1: deterministic, no LLM involved.
	await browser.start()
	await browser.new_tab('https://github.com/browser-use/browser-use')
	await browser.wait_for_load()
	print(await browser.page_info())

	# Layers 2+3: agent with a custom tool and a typed final answer.
	agent = Agent(
		task='Find the star counts of the browser-use and browser-harness repos',
		llm=ChatBrowserUse(),
		browser=browser,
		tools=tools,
		output_model_schema=Repos,
	)
	history = await agent.run()
	print(history.structured_output)


if __name__ == '__main__':
	asyncio.run(main())
