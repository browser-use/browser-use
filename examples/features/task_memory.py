import asyncio
import os

from browser_use import Agent
from browser_use.agent.task.views import TaskMemoryConfig
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

memory_config = TaskMemoryConfig(
	use_local_qdrant=True,
	local_qdrant_path='./qdrant_storage',
)

task = 'Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result'

browser = Browser(
		config=BrowserConfig(
			new_context_config=BrowserContextConfig(
				wait_between_actions=5,
			),
		),
	)
agent = Agent(
	task=task, 
	llm=llm,
	task_memory_config=memory_config,
	browser=browser,
)

async def main():
	await agent.run()

if __name__ == '__main__':
	asyncio.run(main())
