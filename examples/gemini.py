import asyncio
import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.utils import BrowserSessionManager, with_error_handling

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

@with_error_handling()
async def run_script():
	agent = Agent(
		task=(
			'Go to url r/LocalLLaMA subreddit and search for "browser use" in the search bar and click on the first post and find the funniest comment'
		),
		llm=llm,
		max_actions_per_step=4,
		tool_call_in_content=False,
	)
	async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
		await managed_agent.run(max_steps=25)

if __name__ == '__main__':
    run_script()
