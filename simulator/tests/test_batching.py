"""Tests for the batch coordinator and the per-agent proxy (no network, fake LLM)."""

from __future__ import annotations

import asyncio
import time

from simulator.core.batching import BatchCoordinator, BatchLLMProxy


class FakeLLM:
	model = 'qwen-max'
	provider = 'dashscope'
	name = 'qwen-max'
	model_name = 'qwen-max'

	async def ainvoke(self, messages, output_format=None, **kwargs):
		await asyncio.sleep(0.2)  # simulate latency
		return f'reply:{messages}'


async def test_full_batches_dispatch_together():
	coord = BatchCoordinator(FakeLLM(), max_batch=3, max_wait_s=2.0)
	res = await asyncio.gather(*(coord.submit(f'm{i}') for i in range(6)))
	assert res == [f'reply:m{i}' for i in range(6)]
	assert coord.batch_sizes == [3, 3]  # two full batches, no timeout wait


async def test_straggler_flushes_on_timeout():
	coord = BatchCoordinator(FakeLLM(), max_batch=3, max_wait_s=0.4)
	t0 = time.time()
	res = await asyncio.gather(coord.submit('a'), coord.submit('b'))
	assert res == ['reply:a', 'reply:b']
	assert coord.batch_sizes == [2]  # under-full batch flushed by the timer
	assert time.time() - t0 >= 0.4


async def test_count_based_flushes_when_all_active_submit():
	# 3 agents active but max_batch is larger; flush as soon as all 3 active agents submit
	coord = BatchCoordinator(FakeLLM(), max_batch=5, max_wait_s=5.0)
	for _ in range(3):
		coord.enter()
	t0 = time.time()
	res = await asyncio.gather(*(coord.submit(f'm{i}') for i in range(3)))
	assert res == [f'reply:m{i}' for i in range(3)]
	assert coord.batch_sizes == [3]  # flushed at active-count, not max_batch, no timeout wait
	assert time.time() - t0 < 1.0  # immediate, not after max_wait


async def test_leave_releases_waiting_batch():
	# 3 active, only 2 submit; when the 3rd leaves (finishes), the waiting 2 flush immediately
	coord = BatchCoordinator(FakeLLM(), max_batch=3, max_wait_s=5.0)
	for _ in range(3):
		coord.enter()

	async def submit_two():
		return await asyncio.gather(coord.submit('a'), coord.submit('b'))

	task = asyncio.create_task(submit_two())
	await asyncio.sleep(0.1)  # let both land in pending (target is 3, so they wait)
	assert coord.batch_sizes == []
	coord.leave()  # third agent finishes -> target drops to 2 -> flush
	res = await task
	assert res == ['reply:a', 'reply:b']
	assert coord.batch_sizes == [2]


async def test_proxy_delegates_and_forwards():
	coord = BatchCoordinator(FakeLLM(), max_batch=1, max_wait_s=1.0)
	proxy = BatchLLMProxy(coord)
	assert proxy.model == 'qwen-max'  # delegated to the real llm
	assert proxy.provider == 'dashscope'
	assert await proxy.ainvoke('hello') == 'reply:hello'  # forwarded through the coordinator
