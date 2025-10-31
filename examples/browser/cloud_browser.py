"""
Simple example of using Browser-Use cloud browser service.

Prerequisites:
1. Set BROWSER_USE_API_KEY environment variable
2. Active subscription at https://cloud.browser-use.com
"""

import asyncio

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from browser_use import Agent, Browser, ChatOpenAI


async def main():
	"""Basic cloud browser example."""

	print('🌤️ Using Browser-Use Cloud Browser')

	# Create agent with cloud browser enabled
	agent = Agent(
		task='Go to https://github.com/browser-use/browser-use and find the number of stars',
		llm=ChatOpenAI(model='gpt-4.1-mini'),
		browser=Browser(use_cloud=True),  # Enable cloud browser
	)

	try:
		result = await agent.run()
		print(f'✅ Result: {result}')
	except Exception as e:
		print(f'❌ Error: {e}')
		if 'Authentication' in str(e):
			print(
				'💡 Set BROWSER_USE_API_KEY environment variable. You can also create an API key at https://cloud.browser-use.com/new-api-key'
			)


if __name__ == '__main__':
	asyncio.run(main())
