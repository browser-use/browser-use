"""FastAPI SSE demo for StreamingReasoningTracer.

Runs a tiny FastAPI app with two endpoints:
  GET /stream   — SSE feed of ReasoningTrace events while a fake agent runs
  GET /traces   — JSON dump of all accumulated traces after the run

Usage::
    uv run python examples/research_streaming_sse.py

Then open http://localhost:8000/stream in a browser or:
    curl -N http://localhost:8000/stream
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.responses import JSONResponse

from browser_use.research import StreamingReasoningTracer

# Module-level tracer — shared between the background task and the endpoints
tracer = StreamingReasoningTracer(buffer_size=64)


async def _fake_agent_run() -> None:
	"""Simulate an agent completing a short research task."""
	steps = [
		('navigate', {'url': 'https://example.com'}),
		('extract_text', {'selector': 'h1'}),
		('click', {'index': 2}),
		('extract_text', {'selector': '#content'}),
	]
	for step_num, (action, params) in enumerate(steps, start=1):
		tracer.on_step_start(step_num)
		await asyncio.sleep(0.3)  # simulate network latency
		tracer.on_thinking(step_num, f'I should {action} now.')
		tracer.on_action(step_num, action, params)
		await asyncio.sleep(0.2)
		tracer.on_action_result(step_num, action, 'ok')
		tracer.on_step_end(step_num, goal_eval='step complete', memory=f'done step {step_num}')
		await asyncio.sleep(0.1)

	tracer.on_task_done(len(steps), final_result='Research complete — extracted all page content.')


@asynccontextmanager
async def lifespan(app: FastAPI):
	asyncio.create_task(_fake_agent_run())
	yield


app = FastAPI(title='Research Streaming SSE Demo', lifespan=lifespan)


@app.get('/stream')
async def stream_traces():
	"""SSE endpoint — streams ReasoningTrace events as they arrive."""

	async def event_generator():
		async for trace in tracer.stream():
			yield trace.to_sse()

	return StreamingResponse(event_generator(), media_type='text/event-stream')


@app.get('/traces')
async def get_traces():
	"""Returns all accumulated traces as JSON (useful after the run completes)."""
	return JSONResponse([json.loads(t.to_json_line()) for t in tracer.traces()])


if __name__ == '__main__':
	uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')
