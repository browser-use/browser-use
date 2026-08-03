"""Tests for #5362: the wait action reports the duration it actually slept.

The wait action sleeps `min(max(seconds - 1, 0), 30)` but previously reported
the *requested* duration to the LLM, so a 120 s request slept 30 s while the
agent was told it had waited two minutes, and the 30 s cap was invisible.

These tests drive the registered wait action with a stubbed asyncio.sleep so
no real waiting happens, and assert that the reported memory reflects the
actual sleep (including the cap when one was applied).
"""

from browser_use.tools.service import Tools


async def _run_wait(seconds):
	tools = Tools()
	action = tools.registry.registry.actions['wait']
	return await action.function(seconds=seconds)


async def test_wait_reports_actual_duration(monkeypatch):
	"""A 3 s request sleeps 2 s (after the 1 s offset) and must report 2 s."""
	sleeps = []

	async def fake_sleep(seconds):
		sleeps.append(seconds)

	monkeypatch.setattr('asyncio.sleep', fake_sleep)

	result = await _run_wait(3)

	assert sleeps == [2]
	assert result.long_term_memory == 'Waited for 2 seconds'
	assert result.extracted_content == 'Waited for 2 seconds'


async def test_wait_reports_cap_when_capped(monkeypatch):
	"""A 120 s request is capped to a 30 s sleep and the cap must be reported."""
	sleeps = []

	async def fake_sleep(seconds):
		sleeps.append(seconds)

	monkeypatch.setattr('asyncio.sleep', fake_sleep)

	result = await _run_wait(120)

	assert sleeps == [30]
	assert result.long_term_memory == 'Waited for 30 seconds (capped from the requested 120)'
	assert result.extracted_content == 'Waited for 30 seconds (capped from the requested 120)'


async def test_wait_without_cap_has_no_cap_message(monkeypatch):
	"""A request under the cap must not include a cap note."""
	sleeps = []

	async def fake_sleep(seconds):
		sleeps.append(seconds)

	monkeypatch.setattr('asyncio.sleep', fake_sleep)

	result = await _run_wait(30)

	assert sleeps == [29]
	assert result.long_term_memory == 'Waited for 29 seconds'
