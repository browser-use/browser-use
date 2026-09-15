"""Compatibility patches for the pinned ``bubus`` library (browser-use/browser-use#5509).

bubus 1.5.6's ``BaseEvent.__await__`` has a cross-loop contamination bug. When an event is
awaited from inside a handler that holds the global processing lock, ``__await__`` enters a
drain/polling loop that iterates ``EventBus.all_instances`` — the process-global WeakSet of
*every* bus, regardless of which event loop each bus was started on — and calls
``await bus.process_event(...)`` for any bus with a queued event. Handlers therefore run on
the awaiting task's event loop, which in a multi-loop application (e.g. several parallel
agent sessions, each on its own loop) is the *wrong* loop for that bus. They hang forever,
events pile up in the ``started`` state, and the bus eventually hits its 100-event capacity
and ``dispatch()`` raises ``RuntimeError: EventBus at capacity: 100 pending events (100 max)``.

The fix (tracked upstream in browser-use/bubus#30, not yet released into the ``bubus==1.5.6``
pin) is to make the drain loop only touch buses that were started on the current running
loop — every other bus is already drained by its own ``_run_loop`` task on its own loop.

This module carries that fix into browser-use as an idempotent compatibility patch:
- ``EventBus._loop`` records the event loop a bus's ``_start()`` ran on.
- ``BaseEvent.__await__`` skips buses whose ``_loop`` differs from the current running loop
  and buses that are no longer running.

The patch is a no-op when bubus already tracks ``EventBus._loop``, i.e. once upstream ships
the fix.
"""

import asyncio
import logging

_logger = logging.getLogger('bubus')

# Marker attribute set on ``EventBus`` once these patches have been applied.
_PATCH_MARKER = '_browser_use_cross_loop_patched'


def is_bubus_cross_loop_fixed() -> bool:
	"""Return True when the cross-loop drain protection is active.

	Either the local compat patch was applied, or the installed bubus already carries
	the upstream fix (it tracks ``EventBus._loop``).
	"""
	from bubus.service import EventBus

	return getattr(EventBus, _PATCH_MARKER, False) or hasattr(EventBus, '_loop')


def apply_bubus_compat_patches() -> bool:
	"""Apply the local bubus compat patches; idempotent and safe to call repeatedly.

	Returns True when a patch was applied by this call. Returns False (and does nothing)
	when the patches were already applied or when an installed bubus already ships the
	upstream fix (i.e. it tracks ``EventBus._loop``).
	"""
	from bubus.models import BaseEvent
	from bubus.service import EventBus

	if getattr(EventBus, _PATCH_MARKER, False) or hasattr(EventBus, '_loop'):
		return False

	_original_start = EventBus._start  # type: ignore[attr-defined]

	def _patched_start(self: EventBus) -> None:
		"""Record the owning event loop so BaseEvent.__await__ can stay on-loop."""
		_original_start(self)
		try:
			loop = asyncio.get_running_loop()
		except RuntimeError:
			# No loop running: _start() no-ops, nothing to record.
			return
		if self._is_running:
			setattr(self, '_loop', loop)

	setattr(EventBus, '_start', _patched_start)

	def _patched_base_event_await(self: BaseEvent):
		"""bubus.models.BaseEvent.__await__ that never drains another loop's buses."""

		async def wait_for_handlers_to_complete_then_return_event():
			assert self.event_completed_signal is not None

			# If we're inside a handler and this event isn't complete yet,
			# we need to process it immediately to avoid deadlock
			from bubus.service import EventBus, holds_global_lock, inside_handler_context

			if not self.event_completed_signal.is_set() and inside_handler_context.get() and holds_global_lock.get():
				# We're inside a handler and hold the global lock
				# Process events until this one completes

				# Keep processing events from this loop's buses until this event is complete
				max_iterations = 1000  # Prevent infinite loops
				iterations = 0

				current_loop = asyncio.get_running_loop()

				try:
					while not self.event_completed_signal.is_set() and iterations < max_iterations:
						iterations += 1
						processed_any = False

						# Process any queued events on buses owned by THIS event loop only.
						# Create a list copy to avoid "Set changed size during iteration" error
						for bus in list(EventBus.all_instances):
							if not bus or not bus.event_queue:
								continue

							# Only drain running buses that belong to the current event loop.
							# Draining a bus owned by another loop runs its handlers on the wrong
							# loop, where they hang forever and pile up until the bus hits its
							# capacity limit (cross-loop contamination, browser-use/browser-use#5509).
							# Each bus's own _run_loop drains it on its own loop. Skip buses that
							# haven't started (_loop is None) or have been stopped (_is_running is
							# False) — a stopped bus can keep _loop set with events still queued, and
							# nothing should run its handlers after stop().
							if not bus._is_running or getattr(bus, '_loop', None) is not current_loop:
								continue

							# Process one event from this bus if available
							try:
								if bus.event_queue.qsize() > 0:
									event = bus.event_queue.get_nowait()
									await bus.process_event(event)
									bus.event_queue.task_done()
									processed_any = True
									# Check if the event we're waiting for is now complete
									if self.event_completed_signal.is_set():
										break
							except asyncio.QueueEmpty:
								pass

						# Break out of the loop if event completed after processing
						if self.event_completed_signal.is_set():
							break

						if not processed_any:
							# No events to process, yield control and check for cancellation
							try:
								await asyncio.sleep(0)
							except asyncio.CancelledError:
								raise
				except asyncio.CancelledError:
					# Handler was cancelled due to timeout, exit cleanly
					_logger.debug(f'Polling loop cancelled for {self}')
					raise

				if iterations >= max_iterations:
					# logger.error(f'Max iterations reached while waiting for {self}')
					pass
			else:
				# Not in handler context - wait for the event to complete normally
				await self.event_completed_signal.wait()

			# Return the completed event without raising errors.
			# Errors should only be raised when explicitly requested via event_result() methods.
			return self

		return wait_for_handlers_to_complete_then_return_event().__await__()

	setattr(BaseEvent, '__await__', _patched_base_event_await)

	setattr(EventBus, _PATCH_MARKER, True)
	return True
