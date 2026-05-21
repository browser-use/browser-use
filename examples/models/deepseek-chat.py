import asyncio
import os

from browser_use import Agent
from browser_use.llm import ChatDeepSeek

# Add your custom instructions
extend_system_message = """
Remember the most important rules: 
1. When performing a search task, open https://www.google.com/ first for search. 
2. Final output.
"""
deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
if deepseek_api_key is None:
	print('Make sure you have DEEPSEEK_API_KEY:')
	print('export DEEPSEEK_API_KEY=your_key')
	exit(0)


async def main():
	llm = ChatDeepSeek(
		base_url='https://api.deepseek.com/v1',
		model='deepseek-chat',
		api_key=deepseek_api_key,
	)

	agent = Agent(
		task='What should we pay attention to in the recent new rules on tariffs in China-US trade?',
		llm=llm,
		use_vision=False,
		extend_system_message=extend_system_message,
	)
	await agent.run()


asyncio.run(main())
