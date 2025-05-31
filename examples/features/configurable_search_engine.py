import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller

# Initialize the language model
llm = ChatOpenAI(model='gpt-4o')


async def demo_google_search():
	"""Demonstrate using Google search (default)"""

	print('🔍 Demo 1: Google Search (default)')

	agent = Agent(
		task="Search for 'browser automation tools' and click on the first result",
		llm=llm,
		search_engine='google',
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=3)


async def demo_duckduckgo_search():
	"""Demonstrate using DuckDuckGo search"""

	print('\n🔍 Demo 2: DuckDuckGo Search')

	agent = Agent(
		task="Search for 'privacy-focused web browsers' using the configured search engine",
		llm=llm,
		search_engine='duckduckgo',
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=3)


async def demo_bing_search():
	"""Demonstrate using Bing search"""

	print('\n🔍 Demo 3: Bing Search')

	agent = Agent(
		task="Search for 'AI automation frameworks' and note the top results",
		llm=llm,
		search_engine='bing',
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=3)


async def demo_baidu_search():
	"""Demonstrate using Baidu search for Chinese content"""

	print('\n🔍 Demo 4: Baidu Search (Chinese)')

	agent = Agent(
		task="搜索 'browser_use 进展' 并查看搜索结果",
		llm=llm,
		search_engine='baidu',
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=3)


async def demo_controller_configuration():
	"""Demonstrate configuring search engine through Controller"""

	print('\n🔍 Demo 5: Controller Configuration')

	# Create controller with specific search engine
	controller = Controller(search_engine='yahoo')

	agent = Agent(
		task="Search for 'web scraping best practices'",
		llm=llm,
		controller=controller,
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=3)


async def demo_invalid_search_engine():
	"""Demonstrate error handling for invalid search engine"""

	print('\n🔍 Demo 6: Invalid Search Engine Error')

	try:
		agent = Agent(
			task="This won't work",
			llm=llm,
			search_engine='invalid_engine',
		)
	except ValueError as e:
		print(f'✅ Caught expected error: {e}')


async def main():
	"""Main function to run all demos in a single event loop"""
	print('🔍 Configurable Search Engine Demos')
	print('=' * 50)

	await demo_google_search()
	await demo_duckduckgo_search()
	await demo_bing_search()
	await demo_baidu_search()
	await demo_controller_configuration()
	await demo_invalid_search_engine()

	print('\n✅ All demos completed!')


if __name__ == '__main__':
	asyncio.run(main())
