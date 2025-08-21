"""EventBus subclass that applies per-event timeout overrides before dispatch."""

from __future__ import annotations

from typing import Any, Optional

from bubus import EventBus

from .event_timeouts import EventTimeouts


class TimeoutAwareEventBus(EventBus):
    """EventBus that injects timeout overrides on events before dispatching.

    If `event_timeouts` is set, each dispatched event gets its `event_timeout`
    attribute set to the configured override for that event class (if provided),
    falling back to the event's own default otherwise.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._event_timeouts: Optional[EventTimeouts] = None

    def set_timeouts(self, event_timeouts: Optional[EventTimeouts]) -> None:
        self._event_timeouts = event_timeouts

    @property
    def event_timeouts(self) -> Optional[EventTimeouts]:
        return self._event_timeouts

    def dispatch(self, event: 'Any') -> 'Any':  # type: ignore[override]
        # Apply override if configured
        if self._event_timeouts is not None:
            override = self._event_timeouts.resolved_timeout_for_event_class(type(event).__name__)
            if override is not None:
                setattr(event, 'event_timeout', override)
        return super().dispatch(event)
