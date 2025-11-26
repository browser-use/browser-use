"""Cloud browser service integration for browser-use.

This module provides integration with the browser-use cloud browser service.
When cloud_browser=True, it automatically creates a cloud browser instance
and returns the CDP URL for connection.
"""

import logging
import os

import httpx

from browser_use.browser.cloud.views import CloudBrowserAuthError, CloudBrowserError, CloudBrowserResponse, CreateBrowserRequest
from browser_use.sync.auth import CloudAuthConfig

logger = logging.getLogger(__name__)


class CloudBrowserClient:
	"""Client for browser-use cloud browser service."""

	def __init__(self, api_base_url: str = 'https://api.browser-use.com'):
		self.api_base_url = api_base_url
		self.client = httpx.AsyncClient(timeout=30.0)
		self.current_session_id: str | None = None

	async def create_browser(
		self, request: CreateBrowserRequest, extra_headers: dict[str, str] | None = None
	) -> CloudBrowserResponse:
		"""Create a new cloud browser instance. For full docs refer to https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/create-browser-session-browsers-post

		Args:
			request: CreateBrowserRequest object containing browser creation parameters

		Returns:
			CloudBrowserResponse: Contains CDP URL and other browser info
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
				'No authentication token found. Please set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com/new-api-key'
			)

		headers = {'X-Browser-Use-API-Key': api_token, 'Content-Type': 'application/json', **(extra_headers or {})}

		# Convert request to dictionary and exclude unset fields
		request_body = request.model_dump(exclude_unset=True)

		try:
			logger.info('🌤️ Creating cloud browser instance...')

			response = await self.client.post(url, headers=headers, json=request_body)

			if response.status_code == 401:
				raise CloudBrowserAuthError(
					'Authentication failed. Please make sure you have set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com/new-api-key'
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

	async def stop_browser(
		self, session_id: str | None = None, extra_headers: dict[str, str] | None = None
	) -> CloudBrowserResponse:
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
				'No authentication token found. Please set BROWSER_USE_API_KEY environment variable to authenticate with the cloud service. You can also create an API key at https://cloud.browser-use.com/new-api-key'
			)

		headers = {'X-Browser-Use-API-Key': api_token, 'Content-Type': 'application/json', **(extra_headers or {})}

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
