"""
Cloud sync service for sending events to the Browser Use cloud.
"""

import asyncio
import logging
import shutil

import httpx
from bubus import BaseEvent

from browser_use.config import CONFIG
from browser_use.sync.auth import TEMP_USER_ID, DeviceAuthClient

logger = logging.getLogger(__name__)


class CloudSync:
	"""Service for syncing events to the Browser Use cloud"""

	def __init__(self, base_url: str | None = None, enable_auth: bool = True):
		# Backend API URL for all API requests - can be passed directly or defaults to env var
		self.base_url = base_url or CONFIG.BROWSER_USE_CLOUD_API_URL
		self.enable_auth = enable_auth
		self.auth_client = DeviceAuthClient(base_url=self.base_url) if enable_auth else None
		self.pending_events: list[BaseEvent] = []
		self.auth_task = None
		self.session_id: str | None = None

	async def handle_event(self, event: BaseEvent) -> None:
		"""Handle an event by sending it to the cloud"""
		try:
			# Extract session ID from CreateAgentSessionEvent
			if event.event_type == 'CreateAgentSessionEvent' and hasattr(event, 'id'):
				self.session_id = str(event.id)  # type: ignore

			# Start authentication flow on first step (after first LLM response)
			if event.event_type == 'CreateAgentStepEvent' and 'step' in dict(event):
				step = dict(event)['step']
				# logger.debug(f'Got CreateAgentStepEvent with step={step}')
				# Trigger on the first step (step=2 because n_steps is incremented before actions)
				if step == 2 and self.enable_auth and self.auth_client:
					if not hasattr(self, 'auth_task') or self.auth_task is None:
						# Start auth in background
						if self.session_id:
							# logger.info('Triggering auth on first step event')
							# Always run auth to show the cloud URL, even if already authenticated
							self.auth_task = asyncio.create_task(self._background_auth(agent_session_id=self.session_id))
						else:
							logger.warning('Cannot start auth - session_id not set yet')

			# Send event to cloud
			await self._send_event(event)

		except Exception as e:
			logger.error(f'Failed to handle {event.event_type} event: {type(e).__name__}: {e}', exc_info=True)

	async def _send_event(self, event: BaseEvent) -> None:
		"""Send event to cloud API"""
		try:
			headers = {}

			# override user_id on event with auth client user_id if available
			if self.auth_client:
				event.user_id = str(self.auth_client.user_id)  # type: ignore
			else:
				event.user_id = TEMP_USER_ID  # type: ignore

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

				if response.status_code == 401 and self.auth_client and not self.auth_client.is_authenticated:
					# Store event for retry after auth
					self.pending_events.append(event)
				elif response.status_code >= 400:
					# Log error but don't raise - we want to fail silently
					logger.debug(
						f'Failed to send sync event: POST {response.request.url} {response.status_code} - {response.text}'
					)
		except httpx.TimeoutException:
			logger.warning(f'Event send timed out after 10 seconds: {event}')
		except httpx.ConnectError as e:
			# logger.warning(f'⚠️ Failed to connect to cloud service at {self.base_url}: {e}')
			pass
		except httpx.HTTPError as e:
			logger.warning(f'HTTP error sending event {event}: {type(e).__name__}: {e}')
		except Exception as e:
			logger.warning(f'Unexpected error sending event {event}: {type(e).__name__}: {e}')

	async def _background_auth(self, agent_session_id: str) -> None:
		"""Run authentication in background or show cloud URL if already authenticated"""
		assert self.auth_client, 'enable_auth=True must be set before calling CloudSync_background_auth()'
		assert self.session_id, 'session_id must be set before calling CloudSync._background_auth() can fire'
		try:
			# If already authenticated, just show the cloud URL
			if self.auth_client.is_authenticated:
				# Use frontend URL for user-facing links
				frontend_url = CONFIG.BROWSER_USE_CLOUD_UI_URL or self.base_url.replace('//api.', '//cloud.')
				session_url = f'{frontend_url.rstrip("/")}/agent/{agent_session_id}'
				terminal_width, _terminal_height = shutil.get_terminal_size((80, 20))
				logger.info('─' * max(terminal_width - 40, 20) + '\n')
				logger.info('🌐  View the details of this run in Browser Use Cloud:')
				logger.info(f'    👉  {session_url}')
				logger.info('─' * max(terminal_width - 40, 20) + '\n\n')
				return

			# Otherwise run full authentication
			success = await self.auth_client.authenticate(
				agent_session_id=agent_session_id,
				show_instructions=True,
			)

			if success:
				# Resend any pending events
				await self._resend_pending_events()

				# Update WAL events with real user_id
				# await self._update_wal_user_ids(agent_session_id)

		except Exception as e:
			logger.debug(f'Cloud sync authentication failed: {e}')

	async def _resend_pending_events(self) -> None:
		"""Resend events that were queued during auth"""
		if not self.pending_events:
			return

		# Send all pending events
		for event in self.pending_events:
			try:
				await self._send_event(event)
			except Exception as e:
				logger.warning(f'Failed to resend pending event: {e}')

		self.pending_events.clear()

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

	async def wait_for_auth(self) -> None:
		"""Wait for authentication to complete if in progress"""
		if self.auth_task and not self.auth_task.done():
			await self.auth_task

	async def authenticate(self, show_instructions: bool = True) -> bool:
		"""Authenticate with the cloud service"""
		if not self.auth_client:
			return False

		return await self.auth_client.authenticate(agent_session_id=self.session_id, show_instructions=show_instructions)
