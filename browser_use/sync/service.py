"""
Cloud sync service for sending events to the Browser Use cloud.
"""

import logging

import httpx
from bubus import BaseEvent

from browser_use.config import CONFIG
from browser_use.sync.auth import TEMP_USER_ID, DeviceAuthClient

logger = logging.getLogger(__name__)


class CloudSync:
	"""Service for syncing events to the Browser Use cloud"""

	def __init__(self, base_url: str | None = None, allow_session_events_for_auth: bool = False):
		# Backend API URL for all API requests - can be passed directly or defaults to env var
		self.base_url = base_url or CONFIG.BROWSER_USE_CLOUD_API_URL
		self.auth_client = DeviceAuthClient(base_url=self.base_url)
		self.session_id: str | None = None
		self.allow_session_events_for_auth = allow_session_events_for_auth
		self.auth_flow_active = False  # Flag to indicate auth flow is running
		# Check if cloud sync is actually enabled - if not, we should remain silent
		self.enabled = CONFIG.BROWSER_USE_CLOUD_SYNC

	async def handle_event(self, event: BaseEvent) -> None:
		"""Handle an event by sending it to the cloud"""
		try:
			# If cloud sync is disabled, don't handle any events
			if not self.enabled:
				return

			# Extract session ID from CreateAgentSessionEvent
			if event.event_type == 'CreateAgentSessionEvent' and hasattr(event, 'id'):
				self.session_id = str(event.id)  # type: ignore

			# Send events based on authentication status and context
			if self.auth_client.is_authenticated:
				# User is authenticated - send all events
				await self._send_event(event)
			elif self.allow_session_events_for_auth:
				# Special case: allow ALL events during auth flow
				await self._send_event(event)
				# Mark auth flow as active when we see a session event
				if event.event_type == 'CreateAgentSessionEvent':
					self.auth_flow_active = True
			else:
				# User is not authenticated and no auth in progress - don't send anything
				logger.debug(f'Skipping event {event.event_type} - user not authenticated')

		except Exception as e:
			logger.error(f'Failed to handle {event.event_type} event: {type(e).__name__}: {e}', exc_info=True)

	async def _send_event(self, event: BaseEvent) -> None:
		"""Send event to cloud API"""
		try:
			headers = {}

			# Override user_id only if it's not already set to a specific value
			# This allows CLI and other code to explicitly set temp user_id when needed
			if self.auth_client and self.auth_client.is_authenticated:
				# Only override if we're fully authenticated and event doesn't have temp user_id
				current_user_id = getattr(event, 'user_id', None)
				if current_user_id != TEMP_USER_ID:
					setattr(event, 'user_id', str(self.auth_client.user_id))
			else:
				# Set temp user_id if not already set
				if not hasattr(event, 'user_id') or not getattr(event, 'user_id', None):
					setattr(event, 'user_id', TEMP_USER_ID)

			# Add auth headers if available
			if self.auth_client:
				headers.update(self.auth_client.get_headers())

			# Send event (batch format with direct BaseEvent serialization)
			async with httpx.AsyncClient() as client:
				# Serialize event and add device_id to all events
				event_data = event.model_dump(mode='json')
				if self.auth_client and self.auth_client.device_id:
					event_data['device_id'] = self.auth_client.device_id

				response = await client.post(
					f'{self.base_url.rstrip("/")}/api/v1/events',
					json={'events': [event_data]},
					headers=headers,
					timeout=10.0,
				)

				if response.status_code >= 400:
					# Log error but don't raise - we want to fail silently
					logger.debug(
						f'Failed to send sync event: POST {response.request.url} {response.status_code} - {response.text}'
					)
		except httpx.TimeoutException:
			logger.debug(f'Event send timed out after 10 seconds: {event}')
		except httpx.ConnectError as e:
			# logger.warning(f'⚠️ Failed to connect to cloud service at {self.base_url}: {e}')
			pass
		except httpx.HTTPError as e:
			logger.debug(f'HTTP error sending event {event}: {type(e).__name__}: {e}')
		except Exception as e:
			logger.debug(f'Unexpected error sending event {event}: {type(e).__name__}: {e}')

	# async def _update_wal_user_ids(self, session_id: str) -> None:
	# 	"""Update user IDs in WAL file after authentication"""
	# 	try:
	# 		assert self.auth_client, 'Cloud sync must be authenticated to update WAL user ID'

	# 		wal_path = CONFIG.BROWSER_USE_CONFIG_DIR / 'events' / f'{session_id}.jsonl'
	# 		if not await anyio.Path(wal_path).exists():
	# 			raise FileNotFoundError(
	# 				f'CloudSync failed to update saved event user_ids after auth: Agent EventBus WAL file not found: {wal_path}'
	# 			)

	# 		# Read all events
	# 		events = []
	# 		content = await anyio.Path(wal_path).read_text()
	# 		for line in content.splitlines():
	# 			if line.strip():
	# 				events.append(json.loads(line))

	# 		# Update user_id and device_id
	# 		user_id = self.auth_client.user_id
	# 		device_id = self.auth_client.device_id
	# 		for event in events:
	# 			if 'user_id' in event:
	# 				event['user_id'] = user_id
	# 			# Add device_id to all events
	# 			event['device_id'] = device_id

	# 		# Write back
	# 		updated_content = '\n'.join(json.dumps(event) for event in events) + '\n'
	# 		await anyio.Path(wal_path).write_text(updated_content)

	# 	except Exception as e:
	# 		logger.warning(f'Failed to update WAL user IDs: {e}')

	def set_auth_flow_active(self) -> None:
		"""Mark auth flow as active to allow all events"""
		self.auth_flow_active = True

	async def authenticate(self, show_instructions: bool = True) -> bool:
		"""Authenticate with the cloud service"""
		# If cloud sync is disabled, don't authenticate
		if not self.enabled:
			return False

		# Check if already authenticated first
		if self.auth_client.is_authenticated:
			import logging

			logger = logging.getLogger(__name__)
			if show_instructions:
				logger.info('✅ Already authenticated! Skipping OAuth flow.')
			return True

		# Not authenticated - run OAuth flow
		return await self.auth_client.authenticate(agent_session_id=self.session_id, show_instructions=show_instructions)
