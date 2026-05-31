from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from browser_use.agent.runtime.views import BrowserRuntimeEvent, BrowserRuntimeEventTypes


class RuntimeEventRecorder(BaseModel):
	"""Subscriber that records runtime events for debugging, telemetry, or replay."""

	model_config = ConfigDict(validate_assignment=True)

	events: list[BrowserRuntimeEvent] = Field(default_factory=list)

	def __call__(self, event: BrowserRuntimeEvent) -> None:
		self.events.append(event)

	def events_by_type(self, event_type: str) -> list[BrowserRuntimeEvent]:
		return [event for event in self.events if event.event_type == event_type]

	def failure_report(self) -> dict[str, Any]:
		failures = [
			event
			for event in self.events
			if event.event_type.endswith('.failed') or event.event_type in {'tool.failed', 'run.failed'}
		]
		tool_events = [event for event in self.events if event.event_type.startswith('tool.')]
		return {
			'total_events': len(self.events),
			'failure_count': len(failures),
			'failures': [_event_summary(event) for event in failures],
			'last_tool_event': _event_summary(tool_events[-1]) if tool_events else None,
			'last_event': _event_summary(self.events[-1]) if self.events else None,
		}

	def timeline(self, *, include_payload: bool = False) -> list[dict[str, Any]]:
		return [_event_summary(event, include_payload=include_payload) for event in self.events]


class FilteredRuntimeEventCallback(BaseModel):
	"""Subscriber adapter for user callbacks, telemetry sinks, GIF builders, or cloud sync."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	callback: Callable[[BrowserRuntimeEvent], None]
	event_types: set[str] | None = None

	def __call__(self, event: BrowserRuntimeEvent) -> None:
		if self.event_types is not None and event.event_type not in self.event_types:
			return
		self.callback(event)


class FilteredAsyncRuntimeEventCallback(BaseModel):
	"""Async subscriber adapter for side effects that need awaits."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	callback: Callable[[BrowserRuntimeEvent], Any]
	event_types: set[str] | None = None

	async def __call__(self, event: BrowserRuntimeEvent) -> None:
		if self.event_types is not None and event.event_type not in self.event_types:
			return
		result = self.callback(event)
		if inspect.isawaitable(result):
			await result


class AgentStepCallbackSubscriber(BaseModel):
	"""Adapts the legacy new-step callback to model output runtime events."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	callback: Callable[[Any, Any, int], Any]

	async def __call__(self, event: BrowserRuntimeEvent) -> None:
		if event.event_type != BrowserRuntimeEventTypes.MODEL_DELTA:
			return
		browser_state_summary = event.payload.get('browser_state_summary')
		model_output = event.payload.get('model_output')
		step = event.payload.get('step')
		if browser_state_summary is None or model_output is None or not isinstance(step, int):
			return
		result = self.callback(browser_state_summary, model_output, step)
		if inspect.isawaitable(result):
			await result


class AgentDoneCallbackSubscriber(BaseModel):
	"""Adapts the legacy done callback to terminal runtime events."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	callback: Callable[[Any], Any]

	async def __call__(self, event: BrowserRuntimeEvent) -> None:
		if event.event_type != BrowserRuntimeEventTypes.RUN_COMPLETED:
			return
		if not event.payload.get('notify_done_callback'):
			return
		history = event.payload.get('history')
		if history is None:
			return
		is_done = getattr(history, 'is_done', None)
		if callable(is_done) and not is_done():
			return
		result = self.callback(history)
		if inspect.isawaitable(result):
			await result


def _event_summary(event: BrowserRuntimeEvent, *, include_payload: bool = True) -> dict[str, Any]:
	summary: dict[str, Any] = {
		'sequence': event.sequence,
		'event_type': event.event_type,
		'run_id': event.run_id,
		'turn_id': event.turn_id,
		'timestamp': event.timestamp.isoformat(),
	}
	if include_payload:
		summary['payload'] = event.payload
	return summary
