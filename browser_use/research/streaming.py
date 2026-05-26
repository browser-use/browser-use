"""StreamingReasoningTracer — Grok-style live reasoning trace emission.

Hooks into Agent step callbacks and emits structured ReasoningTrace events
as they happen. Supports three consumer patterns:

  1. Async generator (native asyncio / FastAPI SSE)
  2. Callback injection (fire-and-forget; for CLI / logging)
  3. In-memory accumulation (for test assertions)

Wire it up::

	tracer = StreamingReasoningTracer()
	agent = Agent(task="...", llm=llm, browser=browser,
	              on_step_start=tracer.on_step_start,
	              on_step_end=tracer.on_step_end)

	# Consume as async generator (e.g. FastAPI SSE endpoint):
	async def event_stream():
	    async for trace in tracer.stream():
	        yield trace.to_sse()

	# Or just print to console while agent runs:
	tracer.add_sink(lambda t: print(t.to_json_line()))
	await agent.run()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from browser_use.research.views import ReasoningEventType, ReasoningTrace

logger = logging.getLogger(__name__)


class StreamingReasoningTracer:
	"""Collects and streams ReasoningTrace events from a running agent.

	Thread-safety note: all public methods must be called from the same
	event loop as the Agent coroutine.
	"""

	def __init__(self, buffer_size: int = 256) -> None:
		self._queue: asyncio.Queue[ReasoningTrace | None] = asyncio.Queue(maxsize=buffer_size)
		self._traces: list[ReasoningTrace] = []  # in-memory accumulator
		self._sinks: list[Callable[[ReasoningTrace], None]] = []
		self._step = 0
		self._closed = False

	# ── Agent callback hooks ──────────────────────────────────────────────────

	def on_step_start(self, step: int, state: Any = None) -> None:
		"""Call at the beginning of each agent step."""
		self._step = step
		self._emit('step_start', step, {'step': step, 'state': str(state)[:200] if state else None})

	def on_thinking(self, step: int, thought: str) -> None:
		"""Call when the agent emits a chain-of-thought chunk."""
		self._emit('thinking', step, {'thought': thought[:1000]})

	def on_action(self, step: int, action_name: str, params: dict[str, Any]) -> None:
		"""Call when an action is dispatched."""
		self._emit('action', step, {'action': action_name, 'params': params})

	def on_action_result(self, step: int, action_name: str, result: Any) -> None:
		"""Call after an action completes."""
		self._emit('action_result', step, {'action': action_name, 'result': str(result)[:500]})

	def on_step_end(self, step: int, goal_eval: str = '', memory: str = '') -> None:
		"""Call at the end of each agent step."""
		self._emit('step_end', step, {'evaluation': goal_eval[:300], 'memory': memory[:300]})

	def on_task_done(self, step: int, final_result: str = '') -> None:
		"""Call when the agent reports task completion."""
		self._emit('task_done', step, {'result': final_result[:1000]})
		self.close()

	def on_error(self, step: int, error: str) -> None:
		"""Call on agent error."""
		self._emit('error', step, {'error': error[:500]})

	# ── Consumer API ──────────────────────────────────────────────────────────

	def add_sink(self, fn: Callable[[ReasoningTrace], None]) -> None:
		"""Register a callback that receives every trace event synchronously."""
		self._sinks.append(fn)

	async def stream(self) -> AsyncIterator[ReasoningTrace]:
		"""Async generator that yields traces as they arrive.

		Terminates when the tracer is closed (on_task_done or close()).
		"""
		while True:
			trace = await self._queue.get()
			if trace is None:  # sentinel
				break
			yield trace

	def traces(self) -> list[ReasoningTrace]:
		"""Return all accumulated traces (for post-run inspection or test assertions)."""
		return list(self._traces)

	def close(self) -> None:
		"""Signal the stream generator to terminate."""
		if not self._closed:
			self._closed = True
			try:
				self._queue.put_nowait(None)  # sentinel
			except asyncio.QueueFull:
				logger.warning('StreamingReasoningTracer: queue full, sentinel dropped')

	# ── Internal ──────────────────────────────────────────────────────────────

	def _emit(self, event_type: ReasoningEventType, step: int, data: dict[str, Any]) -> None:
		trace = ReasoningTrace(event_type=event_type, step=step, data=data)
		self._traces.append(trace)
		for sink in self._sinks:
			try:
				sink(trace)
			except Exception as exc:
				logger.debug('StreamingReasoningTracer: sink raised %s', exc)
		try:
			self._queue.put_nowait(trace)
		except asyncio.QueueFull:
			logger.debug('StreamingReasoningTracer: buffer full, dropping %s at step %d', event_type, step)
