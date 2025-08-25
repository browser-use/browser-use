import asyncio
import os

from browser_use import Agent
from browser_use.llm import ChatQwen

# Add your custom instructions
extend_system_message = """
Remember the most important rules: 
1. When performing a search task, open https://www.google.com/ first for search. 
2. Final output.
"""

qwen_api_key = os.getenv('QWEN_API_KEY')
if qwen_api_key is None:
	print('Make sure you have QWEN_API_KEY:')
	print('export QWEN_API_KEY=your_key')
	print('Get your API key from Alibaba Cloud Model Studio: https://bailian.console.aliyun.com/')
	exit(0)


async def main():
	llm = ChatQwen(
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		model='qwen-max',
		api_key=qwen_api_key,
	)

	agent = Agent(
		task='What are the latest developments in AI technology? Search for recent news.',
		llm=llm,
		use_vision=False,
		extend_system_message=extend_system_message,
	)
	await agent.run()


asyncio.run(main())
