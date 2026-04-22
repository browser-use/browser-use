import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatKimi

load_dotenv()

# Get API key from environment variable
api_key = os.getenv('KIMI_API_KEY')
if api_key is None:
	print('Make sure you have KIMI_API_KEY set in your .env file')
	print('Get your API key from https://www.kimi.com/code/console/api-keys')
	exit(1)

# Configure Kimi-for-coding model
llm = ChatKimi(
	model='kimi-for-coding',
	api_key=api_key,
)


async def main():
	agent = Agent(
		task='Find the top trending Python repository on GitHub',
		llm=llm,
		use_vision=True,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
