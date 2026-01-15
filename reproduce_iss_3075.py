import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent


async def reproduce():
	# Use a real browser session to verify actual interaction
	# (Assuming user has valid LLM config in env or we use default)

	# We will use Google as a baseline test case for search form
	task = 'unpopular search query for testing 12345'

	print(f"Starting agent with task: Go to google.com and search for '{task}'")

	# Initialize basic agent
	agent = Agent(
		task=f"Go to google.com and search for '{task}'",
		llm=ChatOpenAI(model='gpt-4o'),  # Or generic
	)

	history = await agent.run(max_steps=5)

	# Check if the last state url contains the search query (indicating success)
	# or if the agent reported success.

	last_result = history.history[-1].result
	print(f'Agent finished. Last result: {last_result}')

	# We can also check the final URL from the last valid browser state
	# But for now, let's just see if it crashes or fails to find the element.


if __name__ == '__main__':
	asyncio.run(reproduce())
