import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent, Browser

load_dotenv()

api_key = os.getenv('GROK_API_KEY', '')
if not api_key:
	raise ValueError('GROK_API_KEY is not set')


async def run_agent(task: str, browser: Browser | None = None, max_steps: int = 38):
	browser = browser or Browser()
	agent = Agent(
		task=task,
		use_vision=False,
		llm=ChatOpenAI(model='grok-2-1212', base_url='https://api.x.ai/v1', api_key=SecretStr(api_key)),
		browser=browser,
	)

	await agent.run()
