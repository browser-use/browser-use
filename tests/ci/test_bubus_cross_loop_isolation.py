"""Regression tests for bubus cross-loop contamination (browser-use/browser-use#5509).

bubus 1.5.6's ``BaseEvent.__await__`` has a drain loop that processes events from
*every* ``EventBus`` in the process, regardless of which event loop each bus was
started on. In a multi-loop application (e.g. parallel agent sessions, each on its
own loop) that runs one bus's handlers on another bus's loop, where they hang and
pile up until the bus hits its capacity limit:

    RuntimeError: EventBus at capacity: 100 pending events (100 max)

browser-use carries the upstream fix (browser-use/bubus#30 -- not yet released)
locally in ``browser_use.bubus_compat``. These tests lock the fix in: they fail
when run against an unpatched bubus 1.5.6.
"""

import asyncio
import threading

from bubus import BaseEvent, EventBus

from browser_use.bubus_compat import apply_bubus_compat_patches, is_bubus_cross_loop_fixed


class BlockerEvent(BaseEvent):
	pass


class ProbeEvent(BaseEvent):
	pass


class ParentEvent(BaseEvent):
	pass


def _spin_loop(loop: asyncio.AbstractEventLoop) -> None:
	asyncio.set_event_loop(loop)
	loop.run_forever()


async def _dispatch_probe(bus: EventBus) -> ProbeEvent:
	return bus.dispatch(ProbeEvent())


async def _await_probe(probe: ProbeEvent) -> None:
	await probe


def test_cross_loop_fix_is_active_or_upstream():
	"""The cross-loop guard must be effective (local patch or upstream bubus fix)."""
	assert is_bubus_cross_loop_fixed()


async def test_await_drain_does_not_process_other_loops_buses():
	"""A bus on another loop must never be drained by BaseEvent.__await__ on this loop."""
	apply_bubus_compat_patches()

	loop_a = asyncio.get_running_loop()

	# --- Bus B lives on its own event loop, running in a background thread ---
	loop_b = asyncio.new_event_loop()
	thread = threading.Thread(target=_spin_loop, args=(loop_b,), daemon=True)
	thread.start()

	ran_on: dict[str, int] = {}
	release_blocker = threading.Event()
	bus_a: EventBus | None = None

	async def blocker_handler(event: BlockerEvent) -> None:
		# Occupy bus B's serial processing so its own run loop cannot advance the
		# ProbeEvent. That way the *only* thing that could move the ProbeEvent while
		# the blocker is held is a (buggy) cross-loop drain from loop A.
		while not release_blocker.is_set():  # noqa: ASYNC110
			await asyncio.sleep(0.01)

	async def probe_handler(event: ProbeEvent) -> None:
		ran_on['probe'] = id(asyncio.get_running_loop())

	async def build_bus_b() -> EventBus:
		b = EventBus(name='BusB')
		b.on(BlockerEvent, blocker_handler)
		b.on(ProbeEvent, probe_handler)
		b.dispatch(BlockerEvent())  # starts B's run loop and keeps it busy
		return b

	bus_b = asyncio.run_coroutine_threadsafe(build_bus_b(), loop_b).result(timeout=5)

	try:
		# Create the probe on loop B; it sits queued behind the blocker.
		probe = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_dispatch_probe(bus_b), loop_b))
		await asyncio.sleep(0.1)
		assert bus_b.event_queue is not None and bus_b.event_queue.qsize() >= 1

		# --- Bus A: a handler on loop A awaits bus B's probe event -> enters the drain ---
		bus_a = EventBus(name='BusA')

		async def parent_handler(event: ParentEvent) -> None:
			# Awaiting from inside a handler (holding the global lock) triggers the
			# cross-bus drain loop. Give it a bounded window to (wrongly) pick up the
			# probe from bus B, then stop waiting so the test can assert.
			try:
				await asyncio.wait_for(_await_probe(probe), timeout=0.4)
			except asyncio.TimeoutError:
				pass

		bus_a.on(ParentEvent, parent_handler)
		await bus_a.dispatch(ParentEvent())

		# Give loop A's drain loop a chance to (wrongly) steal the probe from bus B.
		await asyncio.sleep(0.6)

		# The probe belongs to bus B's loop. Loop A must NOT have run it.
		assert ran_on.get('probe') != id(loop_a), "ProbeEvent from bus B ran on bus A's loop — cross-loop contamination"

		# Once bus B is free, its own loop processes the probe — on loop B.
		release_blocker.set()
		for _ in range(200):
			if 'probe' in ran_on:
				break
			await asyncio.sleep(0.05)
		assert ran_on.get('probe') == id(loop_b), f"ProbeEvent did not run on bus B's own loop: {ran_on}"
	finally:
		# Always tear down, even if an assertion above fails, so a failing run
		# never leaks bus B's still-spinning run loop or its background thread
		# into later tests.
		release_blocker.set()
		try:
			asyncio.run_coroutine_threadsafe(bus_b.stop(), loop_b).result(timeout=5)
		finally:
			if bus_a is not None:
				await bus_a.stop()
			loop_b.call_soon_threadsafe(loop_b.stop)
			thread.join(timeout=5)
