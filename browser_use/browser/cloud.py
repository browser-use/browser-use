"""Cloud browser service integration for browser-use.

This module provides integration with the browser-use cloud browser service.
When cloud_browser=True, it automatically creates a cloud browser instance
and returns the CDP URL for connection.
"""

import logging
import os

import httpx
from pydantic import BaseModel, Field

from browser_use.sync.auth import CloudAuthConfig

logger = logging.getLogger(__name__)


class CloudBrowserResponse(BaseModel):
	"""Response from cloud browser API."""

	id: str
	status: str
	liveUrl: str = Field(alias='liveUrl')
	cdpUrl: str = Field(alias='cdpUrl')
	timeoutAt: str = Field(alias='timeoutAt')
	startedAt: str = Field(alias='startedAt')
	finishedAt: str | None = Field(alias='finishedAt', default=None)


class CloudBrowserError(Exception):
	"""Exception raised when cloud browser operations fail."""

	pass


class CloudBrowserAuthError(CloudBrowserError):
	"""Exception raised when cloud browser authentication fails."""

	pass


class CloudBrowserClient:
	"""Client for browser-use cloud browser service."""

	def __init__(self, api_base_url: str = 'https://api.browser-use.com'):
		self.api_base_url = api_base_url
		self.client = httpx.AsyncClient(timeout=30.0)
		self.current_session_id: str | None = None

	async def create_browser(self) -> CloudBrowserResponse:
		"""Create a new cloud browser instance.

		Returns:
			CloudBrowserResponse: Contains CDP URL and other browser info

		Raises:
			CloudBrowserAuthError: If authentication fails
			CloudBrowserError: If browser creation fails
		"""
		url = f'{self.api_base_url}/api/v2/browsers'

		# Try to get API key from environment variable first, then auth config
		api_token = os.getenv('BROWSER_USE_API_KEY')

		if not api_token:
			# Fallback to auth config file
			try:
				auth_config = CloudAuthConfig.load_from_file()
				api_token = auth_config.api_token
			except Exception:
				pass

		if not api_token:
			raise CloudBrowserAuthError(
				'No authentication token found. Please set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com'
			)

		headers = {'X-Browser-Use-API-Key': api_token, 'Content-Type': 'application/json'}

		# Empty request body as per API specification
		request_body = {}

		try:
			logger.info('🌤️ Creating cloud browser instance...')

			response = await self.client.post(url, headers=headers, json=request_body)

			if response.status_code == 401:
				raise CloudBrowserAuthError(
					'Authentication failed. Please make sure you have set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com'
				)
			elif response.status_code == 403:
				raise CloudBrowserAuthError('Access forbidden. Please check your browser-use cloud subscription status.')
			elif not response.is_success:
				error_msg = f'Failed to create cloud browser: HTTP {response.status_code}'
				try:
					error_data = response.json()
					if 'detail' in error_data:
						error_msg += f' - {error_data["detail"]}'
				except Exception:
					pass
				raise CloudBrowserError(error_msg)

			browser_data = response.json()
			browser_response = CloudBrowserResponse(**browser_data)

			# Store session ID for cleanup
			self.current_session_id = browser_response.id

			logger.info(f'🌤️ Cloud browser created successfully: {browser_response.id}')
			logger.debug(f'🌤️ CDP URL: {browser_response.cdpUrl}')
			# Cyan color for live URL
			logger.info(f'\033[36m🔗 Live URL: {browser_response.liveUrl}\033[0m')

			return browser_response

		except httpx.TimeoutException:
			raise CloudBrowserError('Timeout while creating cloud browser. Please try again.')
		except httpx.ConnectError:
			raise CloudBrowserError('Failed to connect to cloud browser service. Please check your internet connection.')
		except Exception as e:
			if isinstance(e, (CloudBrowserError, CloudBrowserAuthError)):
				raise
			raise CloudBrowserError(f'Unexpected error creating cloud browser: {e}')

	async def stop_browser(self, session_id: str | None = None) -> CloudBrowserResponse:
		"""Stop a cloud browser session.

		Args:
			session_id: Session ID to stop. If None, uses current session.

		Returns:
			CloudBrowserResponse: Updated browser info with stopped status

		Raises:
			CloudBrowserAuthError: If authentication fails
			CloudBrowserError: If stopping fails
		"""
		if session_id is None:
			session_id = self.current_session_id

		if not session_id:
			raise CloudBrowserError('No session ID provided and no current session available')

		url = f'{self.api_base_url}/api/v2/browsers/{session_id}'

		# Try to get API key from environment variable first, then auth config
		api_token = os.getenv('BROWSER_USE_API_KEY')

		if not api_token:
			# Fallback to auth config file
			try:
				auth_config = CloudAuthConfig.load_from_file()
				api_token = auth_config.api_token
			except Exception:
				pass

		if not api_token:
			raise CloudBrowserAuthError(
				'No authentication token found. Please set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com'
			)

		headers = {'X-Browser-Use-API-Key': api_token, 'Content-Type': 'application/json'}

		request_body = {'action': 'stop'}

		try:
			logger.info(f'🌤️ Stopping cloud browser session: {session_id}')

			response = await self.client.patch(url, headers=headers, json=request_body)

			if response.status_code == 401:
				raise CloudBrowserAuthError(
					'Authentication failed. Please make sure you have set the BROWSER_USE_API_KEY environment variable to authenticate with the cloud service.'
				)
			elif response.status_code == 404:
				# Session already stopped or doesn't exist - treating as error and clearing session
				logger.debug(f'🌤️ Cloud browser session {session_id} not found (already stopped)')
				# Clear current session if it was this one
				if session_id == self.current_session_id:
					self.current_session_id = None
				raise CloudBrowserError(f'Cloud browser session {session_id} not found')
			elif not response.is_success:
				error_msg = f'Failed to stop cloud browser: HTTP {response.status_code}'
				try:
					error_data = response.json()
					if 'detail' in error_data:
						error_msg += f' - {error_data["detail"]}'
				except Exception:
					pass
				raise CloudBrowserError(error_msg)

			browser_data = response.json()
			browser_response = CloudBrowserResponse(**browser_data)

			# Clear current session if it was this one
			if session_id == self.current_session_id:
				self.current_session_id = None

			logger.info(f'🌤️ Cloud browser session stopped: {browser_response.id}')
			logger.debug(f'🌤️ Status: {browser_response.status}')

			return browser_response

		except httpx.TimeoutException:
			raise CloudBrowserError('Timeout while stopping cloud browser. Please try again.')
		except httpx.ConnectError:
			raise CloudBrowserError('Failed to connect to cloud browser service. Please check your internet connection.')
		except Exception as e:
			if isinstance(e, (CloudBrowserError, CloudBrowserAuthError)):
				raise
			raise CloudBrowserError(f'Unexpected error stopping cloud browser: {e}')

	async def close(self):
		"""Close the HTTP client and cleanup any active sessions."""
		# Try to stop current session if active
		if self.current_session_id:
			try:
				await self.stop_browser()
			except Exception as e:
				logger.debug(f'Failed to stop cloud browser session during cleanup: {e}')

		await self.client.aclose()


# Global client instance
_cloud_client: CloudBrowserClient | None = None


async def get_cloud_browser_cdp_url() -> str:
	"""Get a CDP URL for a new cloud browser instance.

	Returns:
		str: CDP URL for connecting to the cloud browser

	Raises:
		CloudBrowserAuthError: If authentication fails
		CloudBrowserError: If browser creation fails
	"""
	global _cloud_client

	if _cloud_client is None:
		_cloud_client = CloudBrowserClient()

	try:
		browser_response = await _cloud_client.create_browser()
		return browser_response.cdpUrl
	except Exception:
		# Clean up client on error
		if _cloud_client:
			await _cloud_client.close()
			_cloud_client = None
		raise


async def stop_cloud_browser_session(session_id: str | None = None) -> CloudBrowserResponse:
	"""Stop a cloud browser session.

	Args:
		session_id: Session ID to stop. If None, uses current session from global client.

	Returns:
		CloudBrowserResponse: Updated browser info with stopped status

	Raises:
		CloudBrowserAuthError: If authentication fails
		CloudBrowserError: If stopping fails
	"""
	global _cloud_client

	if _cloud_client is None:
		_cloud_client = CloudBrowserClient()

	try:
		return await _cloud_client.stop_browser(session_id)
	except Exception:
		# Don't clean up client on stop errors - session might still be valid
		raise


async def cleanup_cloud_client():
	"""Clean up the global cloud client."""
	global _cloud_client
	if _cloud_client:
		await _cloud_client.close()
		_cloud_client = None
