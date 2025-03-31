import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig, BrowserContextConfig

load_dotenv()

# video https://preview.screen.studio/share/vuq91Ej8
llm = ChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
task = 'go to https://en.wikipedia.org/wiki/Banana and click on buttons on the wikipedia page to go as fast as possible from banna to Quantum mechanics'

browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=-1,
			highlight_elements=False,
		),
	),
)
agent = Agent(task=task, llm=llm, browser=browser, use_vision=False)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
