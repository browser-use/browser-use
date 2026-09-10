"""Regression tests for #5362: wait action must report the duration it actually slept.

Previously wait:
- subtracted 1 second silently (comment claimed -3 and said it was reverted)
- slept min(seconds-1, 30) but reported `seconds` unchanged into long_term_memory
- so a request for 120s slept 30s and told the LLM it waited 120s
"""

from __future__ import annotations

import asyncio

from browser_use.tools.service import Tools


def _wait_fn(tools: Tools):
	return tools.registry.registry.actions['wait'].function


async def test_wait_sleeps_and_reports_requested_duration(monkeypatch):
	"""No silent -1: request 5s → sleep 5s and report 5s."""
	slept: list[float] = []

	async def _record_sleep(seconds: float):
		slept.append(seconds)

	monkeypatch.setattr(asyncio, 'sleep', _record_sleep)

	result = await _wait_fn(Tools())(seconds=5)

	assert slept == [5]
	assert result.error is None
	assert result.long_term_memory == 'Waited for 5 seconds'
	assert result.extracted_content == 'Waited for 5 seconds'
	assert '4' not in (result.long_term_memory or '')


async def test_wait_cap_is_honest_in_memory(monkeypatch):
	"""Request >30s: sleep 30 and tell the model about the cap, not the requested value alone."""
	slept: list[float] = []

	async def _record_sleep(seconds: float):
		slept.append(seconds)

	monkeypatch.setattr(asyncio, 'sleep', _record_sleep)

	result = await _wait_fn(Tools())(seconds=120)

	assert slept == [30]
	assert result.long_term_memory is not None
	assert '30' in result.long_term_memory
	assert '120' in result.long_term_memory  # requested, disclosed
	assert 'capped' in result.long_term_memory.lower()
	# Must not claim we waited the full requested duration as if uncapped
	assert result.long_term_memory != 'Waited for 120 seconds'


async def test_wait_singular_second(monkeypatch):
	slept: list[float] = []

	async def _record_sleep(seconds: float):
		slept.append(seconds)

	monkeypatch.setattr(asyncio, 'sleep', _record_sleep)

	result = await _wait_fn(Tools())(seconds=1)

	assert slept == [1]
	assert result.long_term_memory == 'Waited for 1 second'


async def test_wait_clamps_negative_to_zero(monkeypatch):
	slept: list[float] = []

	async def _record_sleep(seconds: float):
		slept.append(seconds)

	monkeypatch.setattr(asyncio, 'sleep', _record_sleep)

	result = await _wait_fn(Tools())(seconds=-3)

	assert slept == [0]
	assert result.long_term_memory is not None
	assert '0' in result.long_term_memory
