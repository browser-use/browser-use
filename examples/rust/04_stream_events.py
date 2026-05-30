"""
Stream the Rust agent's events live — actually live this time.

The refactored `agent.run_streaming()` returns an async iterator that yields
typed events as the Rust core writes them, instead of dumping a snapshot
after the run has already finished. After the loop ends, `agent.result`
holds the final `AgentRunResult`.

Run:
    python examples/terminal/04_stream_events.py "describe the homepage"
"""

from __future__ import annotations

import asyncio
import sys

from browser_use.rust import Agent, ModelTextDelta, SessionResult, ToolCall


async def main(task: str) -> None:
	agent = Agent(task=task)
	print(f'[live] task: {task}')

	tool_calls = 0
	model_chars = 0
	async for event in agent.run_streaming():
		if isinstance(event, ToolCall):
			tool_calls += 1
			print(f'  · tool[{tool_calls:02d}] {event.tool_name}')
		elif isinstance(event, ModelTextDelta):
			model_chars += len(event.delta)
		elif isinstance(event, SessionResult):
			print(f'  · result: {event.text[:120]}…')

	result = agent.result
	print(f'\n[live] {tool_calls} tool calls · {model_chars} model chars · status={result.status}')
	print(f'[live] final_summary:\n{result.final_summary}')


if __name__ == '__main__':
	task = ' '.join(sys.argv[1:]) or 'go to example.com and describe the homepage'
	asyncio.run(main(task))
