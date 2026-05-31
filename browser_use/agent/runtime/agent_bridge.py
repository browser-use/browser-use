from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)
from browser_use.agent.runtime.subscribers import (
	AgentDoneCallbackSubscriber,
	AgentStepCallbackSubscriber,
	FilteredAsyncRuntimeEventCallback,
)
from browser_use.agent.runtime.views import BrowserAgentSession, BrowserRuntimeEvent, BrowserRuntimeEventTypes


class AgentRuntimeEventBridge(BaseModel):
	"""Connect Agent side effects to runtime stream subscribers."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	agent: Any
	runtime_session: BrowserAgentSession

	def attach(self) -> None:
		stream = self.runtime_session.event_stream
		if self.agent.register_new_step_callback is not None:
			stream.subscribe_async(AgentStepCallbackSubscriber(callback=self.agent.register_new_step_callback))
		if self.agent.register_done_callback is not None:
			stream.subscribe_async(AgentDoneCallbackSubscriber(callback=self.agent.register_done_callback))

		stream.subscribe_async(
			FilteredAsyncRuntimeEventCallback(
				callback=self._dispatch_legacy_cloud_event,
				event_types={
					BrowserRuntimeEventTypes.RUN_STARTED,
					BrowserRuntimeEventTypes.TURN_COMPLETED,
					BrowserRuntimeEventTypes.RUN_COMPLETED,
					BrowserRuntimeEventTypes.RUN_FAILED,
				},
			)
		)
		stream.subscribe_async(
			FilteredAsyncRuntimeEventCallback(
				callback=self._capture_telemetry_from_runtime_event,
				event_types={BrowserRuntimeEventTypes.RUN_COMPLETED, BrowserRuntimeEventTypes.RUN_FAILED},
			)
		)
		stream.subscribe_async(
			FilteredAsyncRuntimeEventCallback(
				callback=self._generate_gif_from_runtime_event,
				event_types={BrowserRuntimeEventTypes.RUN_COMPLETED, BrowserRuntimeEventTypes.RUN_FAILED},
			)
		)

	async def emit_runtime_event(
		self,
		event_type: str,
		*,
		payload: dict[str, Any] | None = None,
		turn_id: str | None = None,
	) -> BrowserRuntimeEvent:
		return await self.runtime_session.event_stream.emit_async(
			run_id=self.runtime_session.run_id,
			turn_id=turn_id,
			event_type=event_type,
			payload=payload,
		)

	async def emit_terminal_event(
		self,
		*,
		max_steps: int,
		agent_run_error: str | None,
		skip_telemetry: bool = False,
		skip_cloud_events: bool = False,
		skip_gif: bool = False,
	) -> BrowserRuntimeEvent:
		event_type = BrowserRuntimeEventTypes.RUN_FAILED if agent_run_error else BrowserRuntimeEventTypes.RUN_COMPLETED
		return await self.emit_runtime_event(
			event_type,
			payload={
				'max_steps': max_steps,
				'agent_run_error': agent_run_error,
				'history': self.agent.history,
				'success': self.agent.history.is_successful(),
				'notify_done_callback': agent_run_error is None and self.agent.history.is_done(),
				'skip_telemetry': skip_telemetry,
				'skip_cloud_events': skip_cloud_events,
				'skip_gif': skip_gif,
			},
		)

	async def _dispatch_legacy_cloud_event(self, event: BrowserRuntimeEvent) -> None:
		"""Bridge observable runtime events to the legacy cloud/eventbus events."""

		if event.payload.get('skip_cloud_events'):
			return

		if event.event_type == BrowserRuntimeEventTypes.RUN_STARTED:
			if not self.agent.state.session_initialized:
				self.agent.logger.debug('📡 Dispatching CreateAgentSessionEvent...')
				self.agent.eventbus.dispatch(CreateAgentSessionEvent.from_agent(self.agent))
				self.agent.state.session_initialized = True

			self.agent.logger.debug('📡 Dispatching CreateAgentTaskEvent...')
			self.agent.eventbus.dispatch(CreateAgentTaskEvent.from_agent(self.agent))
			return

		if event.event_type == BrowserRuntimeEventTypes.TURN_COMPLETED:
			step_event = event.payload.get('legacy_step_event')
			if step_event is not None:
				self.agent.eventbus.dispatch(step_event)
			return

		if event.event_type in {BrowserRuntimeEventTypes.RUN_COMPLETED, BrowserRuntimeEventTypes.RUN_FAILED}:
			self.agent.eventbus.dispatch(UpdateAgentTaskEvent.from_agent(self.agent))

	async def _capture_telemetry_from_runtime_event(self, event: BrowserRuntimeEvent) -> None:
		if event.payload.get('skip_telemetry'):
			return
		max_steps = event.payload.get('max_steps')
		if not isinstance(max_steps, int):
			return
		agent_run_error = event.payload.get('agent_run_error')
		self.agent._log_agent_event(
			max_steps=max_steps,
			agent_run_error=agent_run_error if isinstance(agent_run_error, str) else None,
		)

	async def _generate_gif_from_runtime_event(self, event: BrowserRuntimeEvent) -> None:
		if event.payload.get('skip_gif') or not self.agent.settings.generate_gif:
			return

		output_path = 'agent_history.gif'
		if isinstance(self.agent.settings.generate_gif, str):
			output_path = self.agent.settings.generate_gif

		from browser_use.agent.gif import create_history_gif

		create_history_gif(task=self.agent.task, history=self.agent.history, output_path=output_path)

		if not Path(output_path).exists() or event.payload.get('skip_cloud_events'):
			return

		output_event = await CreateAgentOutputFileEvent.from_agent_and_file(self.agent, output_path)
		self.agent.eventbus.dispatch(output_event)
