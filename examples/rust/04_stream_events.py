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
from datetime import datetime

from browser_use.rust import Agent


def log(message: str) -> None:
	print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


async def main(task: str) -> None:
	agent = Agent(task=task)
	log(f'task: {task}')

	tool_calls = 0
	model_chars = 0
	async for event in agent.run_streaming():
		payload = event.payload
		if event.type == 'session.created':
			log(f'session: {event.session_id}')
		elif event.type == 'model.turn.request':
			log(f'llm turn {payload.get("turn_idx")}: {payload.get("provider")} {payload.get("model")}')
		if event.type == 'tool.started':
			tool_calls += 1
			log(f'tool {tool_calls:02d} start: {payload.get("name")}')
		elif event.type == 'tool.finished':
			log(f'tool done: {payload.get("name") or payload.get("tool")}')
		elif event.type == 'browser_script.completed':
			log(f'browser script: {len(payload.get("summary") or [])} outputs')
		elif event.type == 'token_count':
			log(
				'tokens: '
				f'in={payload.get("input_tokens", 0)} '
				f'out={payload.get("output_tokens", 0)} '
				f'total={payload.get("total_tokens", 0)}'
			)
		elif event.type in {'model.delta', 'model.stream_delta'}:
			model_chars += len(payload.get('delta') or payload.get('text') or '')
		elif event.type in {'session.done', 'session.result'}:
			text = payload.get('result') or payload.get('text') or ''
			log(f'result: {text[:120]}...')

	result = agent.result
	if result is None:
		raise RuntimeError('agent finished without a result')
	print('', flush=True)
	log(f'done: {tool_calls} tool calls, {model_chars} model chars, status={result.status}')
	print(f'final_summary:\n{result.final_summary}', flush=True)


if __name__ == '__main__':
	task = ' '.join(sys.argv[1:]) or 'go to example.com and describe the homepage'
	asyncio.run(main(task))
