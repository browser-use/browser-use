"""Batched LLM inference: gather concurrent agent calls into one dispatched batch.

``BatchCoordinator`` is the batch barrier. Each agent calls ``submit()`` for its
per-step decision; the coordinator flushes a batch when either ``max_batch``
requests have arrived OR ``max_wait`` seconds elapse, dispatches the whole batch
together, and hands each agent back its own result — so requests go out as a
batch and come back as a batch.

``BatchLLMProxy`` is the per-agent facade handed to ``Agent(llm=...)``: it forwards
``ainvoke`` to the shared coordinator and delegates every other attribute to the
real LLM. One proxy per agent keeps browser-use's token-tracking monkey-patch from
stacking across the shared object.
"""

from __future__ import annotations

import asyncio
from typing import Any

from browser_use.llm.base import BaseChatModel


class BatchCoordinator:
	def __init__(self, real_llm: BaseChatModel, max_batch: int, max_wait_s: float):
		self.real = real_llm
		self.max_batch = max_batch
		self.max_wait_s = max_wait_s
		self._pending: list[tuple] = []
		self._lock = asyncio.Lock()
		self._timer: asyncio.TimerHandle | None = None
		self.batch_sizes: list[int] = []  # observed batch sizes, for reporting

	async def submit(self, messages, output_format=None, **kwargs):
		loop = asyncio.get_running_loop()
		fut = loop.create_future()
		async with self._lock:
			self._pending.append((messages, output_format, kwargs, fut))
			if len(self._pending) >= self.max_batch:
				self._cancel_timer()
				batch = self._pending
				self._pending = []
				asyncio.ensure_future(self._dispatch(batch))
			elif self._timer is None:
				self._timer = loop.call_later(self.max_wait_s, self._on_timeout)
		return await fut

	def _cancel_timer(self) -> None:
		if self._timer is not None:
			self._timer.cancel()
			self._timer = None

	def _on_timeout(self) -> None:
		asyncio.ensure_future(self._flush_timeout())

	async def _flush_timeout(self) -> None:
		async with self._lock:
			self._timer = None
			if not self._pending:
				return
			batch = self._pending
			self._pending = []
		await self._dispatch(batch)

	async def _dispatch(self, batch: list[tuple]) -> None:
		self.batch_sizes.append(len(batch))

		async def one(messages, output_format, kwargs, fut):
			try:
				res = await self.real.ainvoke(messages, output_format=output_format, **kwargs)
				if not fut.done():
					fut.set_result(res)
			except Exception as e:  # noqa: BLE001
				if not fut.done():
					fut.set_exception(e)

		await asyncio.gather(*(one(*b) for b in batch))

	def batch_stats(self) -> dict[str, Any]:
		bs = self.batch_sizes
		dist: dict[int, int] = {}
		for s in bs:
			dist[s] = dist.get(s, 0) + 1
		return {
			'num_batches': len(bs),
			'avg_size': round(sum(bs) / len(bs), 2) if bs else 0.0,
			'size_distribution': dict(sorted(dist.items())),
		}


class BatchLLMProxy:
	"""Per-agent LLM facade: forwards ainvoke to the shared coordinator, delegates the rest."""

	def __init__(self, coordinator: BatchCoordinator):
		self._coord = coordinator

	async def ainvoke(self, messages, output_format=None, **kwargs):
		return await self._coord.submit(messages, output_format=output_format, **kwargs)

	def __getattr__(self, name: str):
		if name == '_coord':
			raise AttributeError(name)
		return getattr(self._coord.real, name)
