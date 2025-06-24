"""
OAuth2 Device Authorization Grant flow client for browser-use.
"""

import asyncio
import json
import os
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

from browser_use.config import CONFIG

# Temporary user ID for pre-auth events (matches cloud backend)
TEMP_USER_ID = '99999999-9999-9999-9999-999999999999'


class CloudAuthConfig(BaseModel):
	"""Configuration for cloud authentication"""

	api_token: str | None = None
	user_id: str | None = None
	authorized_at: datetime | None = None

	@classmethod
	def load_from_file(cls) -> 'CloudAuthConfig':
		"""Load auth config from local file"""

		config_path = CONFIG.BROWSER_USE_CONFIG_DIR / 'cloud_auth.json'
		if config_path.exists():
			try:
				with open(config_path) as f:
					data = json.load(f)
				return cls.model_validate(data)
			except Exception:
				# Return empty config if file is corrupted
				pass
		return cls()

	def save_to_file(self) -> None:
		"""Save auth config to local file"""

		CONFIG.BROWSER_USE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

		config_path = CONFIG.BROWSER_USE_CONFIG_DIR / 'cloud_auth.json'
		with open(config_path, 'w') as f:
			json.dump(self.model_dump(mode='json'), f, indent=2, default=str)

		# Set restrictive permissions (owner read/write only) for security
		try:
			os.chmod(config_path, 0o600)
		except Exception:
			# Some systems may not support chmod, continue anyway
			pass


class DeviceAuthClient:
	"""Client for OAuth2 device authorization flow"""

	def __init__(self, base_url: str | None = None, http_client: httpx.AsyncClient | None = None):
		# Backend API URL for OAuth requests - can be passed directly or defaults to env var
		self.base_url = base_url or CONFIG.BROWSER_USE_CLOUD_API_URL
		self.client_id = 'library'
		self.scope = 'read write'

		# If no client provided, we'll create one per request
		self.http_client = http_client

		# Temporary user ID for pre-auth events
		self.temp_user_id = TEMP_USER_ID

		# Load existing auth if available
		self.auth_config = CloudAuthConfig.load_from_file()

	@property
	def is_authenticated(self) -> bool:
		"""Check if we have valid authentication"""
		return bool(self.auth_config.api_token and self.auth_config.user_id)

	@property
	def api_token(self) -> str | None:
		"""Get the current API token"""
		return self.auth_config.api_token

	@property
	def user_id(self) -> str:
		"""Get the current user ID (temporary or real)"""
		return self.auth_config.user_id or self.temp_user_id

	async def start_device_authorization(
		self,
		agent_session_id: str | None = None,
	) -> dict:
		"""
		Start the device authorization flow.
		Returns device authorization details including user code and verification URL.
		"""
		if self.http_client:
			response = await self.http_client.post(
				f'{self.base_url.rstrip("/")}/api/v1/oauth/device/authorize',
				data={
					'client_id': self.client_id,
					'scope': self.scope,
					'agent_session_id': agent_session_id,
				},
			)
			response.raise_for_status()
			return response.json()
		else:
			async with httpx.AsyncClient() as client:
				response = await client.post(
					f'{self.base_url.rstrip("/")}/api/v1/oauth/device/authorize',
					data={
						'client_id': self.client_id,
						'scope': self.scope,
						'agent_session_id': agent_session_id,
					},
				)
				response.raise_for_status()
				return response.json()

	async def poll_for_token(
		self,
		device_code: str,
		interval: float = 3.0,
		timeout: float = 1800.0,
	) -> dict | None:
		"""
		Poll for the access token.
		Returns token info when authorized, None if timeout.
		"""
		start_time = time.time()

		if self.http_client:
			# Use injected client for all requests
			while time.time() - start_time < timeout:
				try:
					response = await self.http_client.post(
						f'{self.base_url.rstrip("/")}/api/v1/oauth/device/token',
						data={
							'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
							'device_code': device_code,
							'client_id': self.client_id,
						},
					)

					if response.status_code == 200:
						data = response.json()

						# Check for pending authorization
						if data.get('error') == 'authorization_pending':
							await asyncio.sleep(interval)
							continue

						# Check for slow down
						if data.get('error') == 'slow_down':
							interval = data.get('interval', interval * 2)
							await asyncio.sleep(interval)
							continue

						# Check for other errors
						if 'error' in data:
							print(f'Error: {data.get("error_description", data["error"])}')
							return None

						# Success! We have a token
						if 'access_token' in data:
							return data

					elif response.status_code == 400:
						# Error response
						data = response.json()
						if data.get('error') not in ['authorization_pending', 'slow_down']:
							print(f'Error: {data.get("error_description", "Unknown error")}')
							return None

					else:
						print(f'Unexpected status code: {response.status_code}')
						return None

				except Exception as e:
					print(f'Error polling for token: {e}')

				await asyncio.sleep(interval)
		else:
			# Create a new client for polling
			async with httpx.AsyncClient() as client:
				while time.time() - start_time < timeout:
					try:
						response = await client.post(
							f'{self.base_url.rstrip("/")}/api/v1/oauth/device/token',
							data={
								'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
								'device_code': device_code,
								'client_id': self.client_id,
							},
						)

						if response.status_code == 200:
							data = response.json()

							# Check for pending authorization
							if data.get('error') == 'authorization_pending':
								await asyncio.sleep(interval)
								continue

							# Check for slow down
							if data.get('error') == 'slow_down':
								interval = data.get('interval', interval * 2)
								await asyncio.sleep(interval)
								continue

							# Check for other errors
							if 'error' in data:
								print(f'Error: {data.get("error_description", data["error"])}')
								return None

							# Success! We have a token
							if 'access_token' in data:
								return data

						elif response.status_code == 400:
							# Error response
							data = response.json()
							if data.get('error') not in ['authorization_pending', 'slow_down']:
								print(f'Error: {data.get("error_description", "Unknown error")}')
								return None

						else:
							print(f'Unexpected status code: {response.status_code}')
							return None

					except Exception as e:
						print(f'Error polling for token: {e}')

					await asyncio.sleep(interval)

		return None

	async def authenticate(
		self,
		agent_session_id: str | None = None,
		show_instructions: bool = True,
	) -> bool:
		"""
		Run the full authentication flow.
		Returns True if authentication successful.
		"""
		import logging

		logger = logging.getLogger(__name__)

		try:
			# Start device authorization
			device_auth = await self.start_device_authorization(agent_session_id)

			# Use frontend URL for user-facing links
			frontend_url = CONFIG.BROWSER_USE_CLOUD_UI_URL or self.base_url.replace('//api.', '//cloud.')

			# Replace backend URL with frontend URL in verification URIs
			verification_uri = device_auth['verification_uri'].replace(self.base_url, frontend_url)
			verification_uri_complete = device_auth['verification_uri_complete'].replace(self.base_url, frontend_url)

			if show_instructions:
				logger.info('\n\n' + '─' * 70)
				logger.info('🌐  View the details of this run in Browser Use Cloud:')
				logger.info(f'    👉  {verification_uri_complete}')
				logger.info('─' * 70 + '\n')

			# Poll for token
			token_data = await self.poll_for_token(
				device_code=device_auth['device_code'],
				interval=device_auth.get('interval', 5),
			)

			if token_data and token_data.get('access_token'):
				# Save authentication
				self.auth_config.api_token = token_data['access_token']
				self.auth_config.user_id = token_data.get('user_id', self.temp_user_id)
				self.auth_config.authorized_at = datetime.now()
				self.auth_config.save_to_file()

				if show_instructions:
					logger.info('✅  Authentication successful! Cloud sync is now enabled.')

				return True

		except Exception as e:
			# Log the error details for debugging
			if hasattr(e, 'response'):
				response = getattr(e, 'response')
				if hasattr(response, 'status_code') and hasattr(response, 'text'):
					logger.debug(
						f'Failed to get pre-auth token for cloud sync: HTTP {response.request.url} {response.status_code} - {response.text}'
					)
				else:
					logger.debug(f'Failed to get pre-auth token for cloud sync: {type(e).__name__}: {e}')
			else:
				logger.debug(f'Failed to get pre-auth token for cloud sync: {type(e).__name__}: {e}')

		if show_instructions:
			logger.info('❌ Authentication failed or timed out')

		return False

	def get_headers(self) -> dict:
		"""Get headers for API requests"""
		if self.api_token:
			return {'Authorization': f'Bearer {self.api_token}'}
		return {}

	def clear_auth(self) -> None:
		"""Clear stored authentication"""
		self.auth_config = CloudAuthConfig()
		self.auth_config.save_to_file()
