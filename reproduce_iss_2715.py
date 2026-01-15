import asyncio
from unittest.mock import MagicMock

from browser_use import Agent


# Mock LLM to avoid dependencies
class MockLLM:
	def __init__(self, model='gpt-4o'):
		self.model = model
		self.provider = 'openai'

	def invoke(self, messages):
		# Return a fake AIMessage
		mock_msg = MagicMock()
		mock_msg.content = 'Next step: done'
		mock_msg.tool_calls = []
		return mock_msg


async def reproduce():
	url = 'https://www.bryanbraun.com/infinitely-nested-iframes/3.html'
	print(f'Reproducing #2715 with URL: {url}')

	# We can't easily mock the full Agent flow without a real LLM for the output parser logic.
	# But for the crash (DOM build), it happens *before* the LLM call usually, during state observation.
	# Or in the initial step.

	try:
		from langchain_openai import ChatOpenAI

		llm = ChatOpenAI(model='gpt-4o')
	except ImportError:
		print('Warning: langchain_openai not found, using MockLLM')
		llm = MockLLM()

	agent = Agent(
		task=f'Go to {url}',
		llm=llm,
	)

	try:
		# We just want to trigger the initial navigation and state capture
		# The crash happens in the watchdog during _build_dom_tree
		await agent.run(max_steps=1)
		print('✅ DOM Tree built successfully.')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	asyncio.run(reproduce())
