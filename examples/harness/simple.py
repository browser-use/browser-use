"""Harness-backed agent: same Agent surface, but the engine is browser-harness
driving your real Chrome over CDP (install with: pip install 'browser-harness[sdk]').

The only difference from examples/simple.py is the import path.
"""

from browser_use import ChatBrowserUse
from browser_use.harness import Agent

agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=ChatBrowserUse(),
)
agent.run_sync()
