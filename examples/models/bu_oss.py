"""
Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse

load_dotenv()

try:
	from lmnr import Laminar

	Laminar.initialize()
except ImportError:
	pass

# Point to local llm-use server for testing
llm = ChatBrowserUse(
	model='browser-use/bu-30b-a3b-preview',  # BU Open Source Model!!
)

agent = Agent(
	task='Find the number of stars of browser-use and stagehand. Tell me which one has more stars :)',
	llm=llm,
	flash_mode=True,
)
agent.run_sync()
