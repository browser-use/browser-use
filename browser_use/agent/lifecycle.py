"""Agent lifecycle and public control helpers."""

import asyncio
import gc
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from browser_use.agent.views import AgentHistoryList, AgentState
from browser_use.browser import BrowserSession
from browser_use.browser.events import _get_timeout

AgentHookFunc = Callable[[Any], Awaitable[None]]


class AgentLifecycleMixin:
	browser_session: BrowserSession | None
	history: AgentHistoryList
	logger: logging.Logger
	sensitive_data: dict[str, str | dict[str, str]] | None
	skill_service: Any | None
	state: AgentState
	_external_pause_event: asyncio.Event

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the history to a file with sensitive data filtering."""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path, sensitive_data=self.sensitive_data)

	def pause(self) -> None:
		"""Pause the agent before the next step."""
		print('\n\n⏸️ Paused the agent and left the browser open.\n\tPress [Enter] to resume or [Ctrl+C] again to quit.')
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume the agent."""
		print('----------------------------------------------------------------------')
		print('▶️  Resuming agent execution where it left off...\n')
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the agent."""
		self.logger.info('⏹️ Agent stopping')
		self.state.stopped = True
		self._external_pause_event.set()

	async def close(self) -> None:
		"""Close all resources."""
		try:
			if self.browser_session is not None:
				if not self.browser_session.browser_profile.keep_alive:
					await self.browser_session.kill()
				else:
					await self.browser_session.event_bus.stop(
						clear=False,
						timeout=_get_timeout('TIMEOUT_BrowserSessionEventBusStopOnAgentClose', 1.0),
					)
					try:
						self.browser_session.event_bus.event_queue = None
						self.browser_session.event_bus._on_idle = None
					except Exception:
						pass

			if self.skill_service is not None:
				await self.skill_service.close()

			gc.collect()

			import threading

			threads = threading.enumerate()
			self.logger.debug(f'🧵 Remaining threads ({len(threads)}): {[t.name for t in threads]}')

			tasks = asyncio.all_tasks(asyncio.get_event_loop())
			other_tasks = [t for t in tasks if t != asyncio.current_task()]
			if other_tasks:
				self.logger.debug(f'⚡ Remaining asyncio tasks ({len(other_tasks)}):')
				for task in other_tasks[:10]:
					self.logger.debug(f'  - {task.get_name()}: {task}')

		except Exception as e:
			self.logger.error(f'Error during cleanup: {e}')

	async def authenticate_cloud_sync(self, show_instructions: bool = True) -> bool:
		"""Cloud sync authentication is no longer available."""
		self.logger.warning('Cloud sync has been removed and is no longer available')
		return False

	def run_sync(
		self,
		max_steps: int = 500,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[Any]:
		"""Synchronous wrapper around the async run method for easier usage without asyncio."""
		run = getattr(self, 'run')
		return asyncio.run(run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))
