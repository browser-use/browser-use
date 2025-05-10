import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent, Browser

load_dotenv()

api_key_groq = os.getenv('GROQ_API_KEY', '')
if not api_key_groq:
	raise ValueError('GROQ_API_KEY is not set')


async def run_agent(task: str, browser: Browser | None = None, max_steps: int = 38):
	browser = browser or Browser()
	llm = ChatOpenAI(
		base_url='https://api.groq.com/openai/v1',
		api_key=SecretStr(api_key_groq),
		model='meta-llama/llama-4-maverick-17b-128e-instruct',
		temperature=0.0,
	)
	agent = Agent(task=task, llm=llm, browser=browser, use_vision=False)
	result = await agent.run(max_steps=max_steps)
	return result


if __name__ == '__main__':
	task = "Find an editor's choice review with a score of 10 in the boardgame category on ign."
	asyncio.run(run_agent(task))
