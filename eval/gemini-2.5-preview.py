import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent, Browser

load_dotenv()

api_key = os.getenv('GOOGLE_API_KEY', '')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')


async def run_agent(task: str, browser: Browser | None = None, max_steps: int = 38):
	browser = browser or Browser()
	llm = ChatGoogleGenerativeAI(model='gemini-2.5-pro-preview-03-25', api_key=SecretStr(api_key))
	agent = Agent(task=task, llm=llm, browser=browser)
	result = await agent.run(max_steps=max_steps)
	return result
