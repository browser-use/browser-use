import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.utils import BrowserSessionManager, with_error_handling

# dotenv
load_dotenv()

api_key = os.getenv('DEEPSEEK_API_KEY', '')
if not api_key:
	raise ValueError('DEEPSEEK_API_KEY is not set')


@with_error_handling()
async def run_script():
	agent = Agent(
		task=(
			'1. Go to https://www.reddit.com/r/LocalLLaMA '
			"2. Search for 'browser use' in the search bar"
			'3. Click on first result'
			'4. Return the first comment'
		),
		llm=ChatOpenAI(
			base_url='https://api.deepseek.com/v1',
			model='deepseek-chat',
			api_key=SecretStr(api_key),
		),
		tool_call_in_content=True,
		use_vision=False,
	)
	async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
		await managed_agent.run()

if __name__ == '__main__':
    run_script()
