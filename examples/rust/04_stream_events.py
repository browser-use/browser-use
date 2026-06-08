"""
Stream the Rust agent's events live — actually live this time.

The refactored `agent.run_streaming()` returns an async iterator that yields
typed events as the Rust core writes them, instead of dumping a snapshot
after the run has already finished. After the loop ends, `agent.result`
holds the final `AgentRunResult`.

Run:
    python examples/rust/04_stream_events.py "describe the homepage"
"""

from __future__ import annotations

import asyncio
import sys

from browser_use.rust import Agent


async def main(task: str) -> None:
	agent = Agent(task=task)
	print(f'[live] task: {task}')

	tool_calls = 0
	model_chars = 0
	async for event in agent.run_streaming():
		if event.type == 'tool.started':
			tool_calls += 1
			print(f'  · tool[{tool_calls:02d}] {event.payload.get("name")}')
		elif event.type in {'model.delta', 'model.stream_delta'}:
			model_chars += len(event.payload.get('delta') or event.payload.get('text') or '')
		elif event.type in {'session.done', 'session.result'}:
			text = event.payload.get('result') or event.payload.get('text') or ''
			print(f'  · result: {text[:120]}…')

	result = agent.result
	if result is None:
		raise RuntimeError('agent finished without a result')
	print(f'\n[live] {tool_calls} tool calls · {model_chars} model chars · status={result.status}')
	print(f'[live] final_summary:\n{result.final_summary}')


if __name__ == '__main__':
	task = ' '.join(sys.argv[1:]) or 'go to example.com and describe the homepage'
	asyncio.run(main(task))
