"""Network watchdog for monitoring and inspecting network traffic (XHR/Fetch)."""

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import (
	BrowserStateRequestEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	from cdp_use.cdp.network import (
		LoadingFailedEvent,
		RequestWillBeSentEvent,
		ResponseReceivedEvent,
	)
	from cdp_use.cdp.target import SessionID, TargetID


@dataclass
class NetworkLogEntry:
	"""Represents a single network request/response cycle."""

	request_id: str
	url: str
	method: str
	resource_type: str
	start_time: float
	status: int | None = None
	status_text: str | None = None
	mime_type: str | None = None
	error_text: str | None = None
	response_headers: dict[str, str] = field(default_factory=dict)

	def to_string(self) -> str:
		"""Compact string representation for LLM consumption."""
		status_str = str(self.status) if self.status else (f'FAILED({self.error_text})' if self.error_text else 'PENDING')
		return f'[{self.method}] {status_str} {self.url} ({self.resource_type})'


class NetworkWatchdog(BaseWatchdog):
	"""
	Monitors network traffic to allow agents to inspect API calls and extracting data directly.
	"""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		TabCreatedEvent,
		BrowserStateRequestEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	# Configuration
	max_logs_per_tab: int = 100
	ignored_resource_types: set[str] = {
		'Image',
		'Stylesheet',
		'Font',
		'Media',
		'Manifest',
		'Other',
	}

	# Private state
	# Maps TargetID -> Deque of logs
	_network_logs: dict[str, deque[NetworkLogEntry]] = PrivateAttr(default_factory=dict)
	_monitored_targets: set[str] = PrivateAttr(default_factory=set)

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Attach network monitoring to new tabs."""
		if event.target_id:
			await self.attach_to_target(event.target_id)

	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> None:
		"""
		Optional: Inject network summary into browser state if needed.
		Currently just ensures the current target is attached.
		"""
		if self.browser_session.agent_focus_target_id:
			await self.attach_to_target(self.browser_session.agent_focus_target_id)

	async def attach_to_target(self, target_id: 'TargetID') -> None:
		"""Initialize network monitoring for a specific target."""
		if target_id in self._monitored_targets:
			return

		try:
			# Get session without focusing (background monitoring)
			session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Initialize log storage for this target
			if target_id not in self._network_logs:
				self._network_logs[target_id] = deque(maxlen=self.max_logs_per_tab)

			# Enable Network domain
			await session.cdp_client.send.Network.enable(session_id=session.session_id)

			# Define handlers
			def on_request(event: 'RequestWillBeSentEvent', _sid: 'SessionID | None') -> None:
				resource_type = event.get('type', 'Unknown')

				# Filter noise
				if resource_type in self.ignored_resource_types:
					return

				entry = NetworkLogEntry(
					request_id=event['requestId'],
					url=event['request']['url'],
					method=event['request']['method'],
					resource_type=resource_type,
					start_time=event['wallTime'],
				)
				self._network_logs[target_id].append(entry)

			def on_response(event: 'ResponseReceivedEvent', _sid: 'SessionID | None') -> None:
				req_id = event['requestId']
				response = event['response']

				# Find entry in reverse (most recent first)
				for entry in reversed(self._network_logs[target_id]):
					if entry.request_id == req_id:
						entry.status = response['status']
						entry.status_text = response['statusText']
						entry.mime_type = response['mimeType']
						# Store headers for potential debugging
						if 'headers' in response:
							entry.response_headers = {k: str(v) for k, v in response['headers'].items()}
						break

			def on_failure(event: 'LoadingFailedEvent', _sid: 'SessionID | None') -> None:
				req_id = event['requestId']
				for entry in reversed(self._network_logs[target_id]):
					if entry.request_id == req_id:
						entry.error_text = event['errorText']
						# Don't overwrite if we already have a status (e.g. 404 is a failure but has status)
						if entry.status is None:
							entry.status = 0
						break

			# Register handlers
			session.cdp_client.register.Network.requestWillBeSent(on_request)
			session.cdp_client.register.Network.responseReceived(on_response)
			session.cdp_client.register.Network.loadingFailed(on_failure)

			self._monitored_targets.add(target_id)
			self.logger.debug(f'[NetworkWatchdog] Attached to target {target_id[-4:]}')

		except Exception as e:
			self.logger.warning(f'[NetworkWatchdog] Failed to attach to {target_id[-4:]}: {e}')

	def get_traffic_log(self, target_id: 'TargetID') -> list[NetworkLogEntry]:
		"""Get list of network logs for a target."""
		if target_id not in self._network_logs:
			return []
		return list(self._network_logs[target_id])

	async def get_response_body(self, target_id: 'TargetID', request_id: str) -> str | None:
		"""
		Fetch the response body for a specific request ID using CDP.
		Returns None if body is unavailable or empty.
		"""
		try:
			session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			result = await session.cdp_client.send.Network.getResponseBody(
				params={'requestId': request_id}, session_id=session.session_id
			)

			return result.get('body')
		except Exception as e:
			# Common error: "No resource with given identifier found" if request is too old or failed
			self.logger.debug(f'[NetworkWatchdog] Failed to get body for {request_id}: {e}')
			return None
