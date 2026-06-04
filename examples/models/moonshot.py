import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

# Get API key from environment variable
api_key = os.getenv('MOONSHOT_API_KEY')
if api_key is None:
	print('Make sure you have MOONSHOT_API_KEY set in your .env file')
	print('Get your API key from https://platform.moonshot.ai/console/api-keys ')
	exit(1)

# Configure Moonshot AI model
llm = ChatOpenAI(
	model='kimi-k2-thinking',
	base_url='https://api.moonshot.ai/v1',
	api_key=api_key,
	add_schema_to_system_prompt=True,
	remove_min_items_from_schema=True,  # Moonshot doesn't support minItems in JSON schema
	remove_defaults_from_schema=True,  # Moonshot doesn't allow default values with anyOf
)


async def main():
	agent = Agent(
		task='Search for the latest news about AI and summarize the top 3 articles',
		llm=llm,
		flash_mode=True,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
