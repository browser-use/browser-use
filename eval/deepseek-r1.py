import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent

load_dotenv()

api_key_deepseek = os.getenv('DEEPSEEK_API_KEY', '')
if not api_key_deepseek:
	raise ValueError('DEEPSEEK_API_KEY is not set')


async def run_agent(task: str, max_steps: int = 38):
	llm = ChatOpenAI(
		base_url='https://api.deepseek.com/v1',
		model='deepseek-reasoner',
		api_key=SecretStr(api_key_deepseek),
	)
	agent = Agent(task=task, llm=llm, use_vision=False)
	result = await agent.run(max_steps=max_steps)
	return result
