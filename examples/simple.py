"""
Setup:
1. Get your API key from https://cloud.browser-use.com/dashboard/api
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse

load_dotenv()

agent = Agent(
	task='Find the number of stars of the following repos: browser-use, playwright, stagehand, react, nextjs',
	llm=ChatBrowserUse(),
)
agent.run_sync()
