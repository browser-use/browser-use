import asyncio
import time

from browser_use.event_bus import EventBus
from bubus import BaseEvent


class SleepEvent(BaseEvent[None]):
	"""Simple event carrying a sleep delay used for timing tests."""

	event_type: str = 'SleepEvent'
	delay: float = 0.0


async def _sleep_handler(event: SleepEvent) -> None:
	await asyncio.sleep(event.delay)


async def test_event_buses_run_in_parallel():
	"""Ensure separate EventBus instances don't serialize each other."""

	bus1 = EventBus(name='bus1')
	bus2 = EventBus(name='bus2')

	bus1.on(SleepEvent, _sleep_handler)
	bus2.on(SleepEvent, _sleep_handler)

	start = time.perf_counter()
	bus1.dispatch(SleepEvent(delay=0.4))
	bus2.dispatch(SleepEvent(delay=0.4))

	try:
		await asyncio.wait_for(
			asyncio.gather(bus1.wait_until_idle(timeout=2.0), bus2.wait_until_idle(timeout=2.0)),
			timeout=2.0,
		)
	finally:
		await asyncio.gather(bus1.stop(clear=True), bus2.stop(clear=True))

	elapsed = time.perf_counter() - start

	# If buses ran serially the runtime would be ~=0.8s; ensure we stay well below that.
	assert elapsed < 0.75
