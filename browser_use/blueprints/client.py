"""
HTTP client for communicating with the Blueprint backend.

Handles blueprint discovery (GET /list) and execution (POST /{group}/{endpoint}).
"""

import logging
import os
from typing import Any

import httpx
from pydantic import ValidationError

from browser_use.blueprints.views import (
	Blueprint,
	BlueprintErrorInfo,
	BlueprintExecutionRequest,
	BlueprintExecutionResponse,
	BlueprintListResponse,
)

logger = logging.getLogger(__name__)


class BlueprintClient:
	"""Client for communicating with the Blueprint backend."""

	def __init__(
		self,
		base_url: str = 'https://blueprint-production-cdc8.up.railway.app',
		api_key: str | None = None,
		timeout: float = 10.0,
	):
		"""
		Initialize the blueprint client.

		Args:
		    base_url: Base URL of the blueprint backend
		    api_key: API key for authentication (reads from BROWSER_USE_API_KEY env var if not provided)
		    timeout: Request timeout in seconds
		"""
		self.base_url = base_url.rstrip('/')
		self.api_key = api_key or os.getenv('BROWSER_USE_API_KEY')
		self.timeout = timeout
		self._client: httpx.AsyncClient | None = None
		self._api_key_warning_logged = False

	async def _get_client(self) -> httpx.AsyncClient:
		"""Get or create the HTTP client."""
		if self._client is None:
			headers = {}
			if self.api_key:
				headers['Authorization'] = f'Bearer {self.api_key}'
				headers['X-API-Key'] = self.api_key

			self._client = httpx.AsyncClient(
				base_url=self.base_url,
				headers=headers,
				timeout=self.timeout,
				follow_redirects=True,
			)
		return self._client

	async def close(self) -> None:
		"""Close the HTTP client."""
		if self._client:
			await self._client.aclose()
			self._client = None

	async def list_blueprints(self, domain: str) -> list[Blueprint]:
		"""
		Fetch available blueprints for a domain.

		Args:
		    domain: Domain to query (e.g., 'amazon.com', 'github.com')

		Returns:
		    List of available Blueprint objects

		Raises:
		    httpx.HTTPError: If the request fails
		"""
		if not self.api_key:
			if not self._api_key_warning_logged:
				logger.warning(
					'BROWSER_USE_API_KEY not set - blueprint integration disabled. '
					'Set BROWSER_USE_API_KEY environment variable to enable dynamic blueprints.'
				)
				self._api_key_warning_logged = True
			return []

		try:
			client = await self._get_client()
			response = await client.get('/list', params={'domain': domain})
			response.raise_for_status()

			# Parse response
			try:
				list_response = BlueprintListResponse.model_validate(response.json())
				logger.debug(f'📘 Found {len(list_response.tools)} blueprints for domain {domain}')
				return list_response.tools
			except ValidationError as e:
				logger.error(f'Failed to parse blueprint list response: {e}')
				return []

		except httpx.HTTPStatusError as e:
			if e.response.status_code == 400:
				logger.warning(f'Blueprint backend rejected request for domain {domain}: {e}')
			elif e.response.status_code == 401:
				logger.error('Blueprint backend authentication failed - check BROWSER_USE_API_KEY')
			else:
				logger.error(f'Blueprint backend returned error {e.response.status_code}: {e}')
			return []
		except httpx.ConnectError:
			logger.debug(f'Blueprint backend not reachable at {self.base_url} - blueprints disabled')
			return []
		except httpx.TimeoutException:
			logger.warning(f'Blueprint backend request timed out for domain {domain}')
			return []
		except Exception as e:
			logger.error(f'Unexpected error fetching blueprints for {domain}: {type(e).__name__}: {e}')
			return []

	async def execute_blueprint(
		self,
		group: str,
		endpoint: str,
		parameters: dict[str, Any],
		blueprint_id: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> BlueprintExecutionResponse:
		"""
		Execute a blueprint.

		Args:
		    group: Blueprint group (e.g., 'amazon', 'github')
		    endpoint: Blueprint endpoint (e.g., 'get_reviews')
		    parameters: Execution parameters
		    blueprint_id: Optional blueprint ID (defaults to {group}_{endpoint})
		    metadata: Optional request metadata

		Returns:
		    BlueprintExecutionResponse with success status and data/error

		Raises:
		    httpx.HTTPError: If the request fails at the HTTP level
		"""
		if not self.api_key:
			logger.warning('Cannot execute blueprint - BROWSER_USE_API_KEY not set')
			return BlueprintExecutionResponse(
				success=False,
				data=None,
				error=BlueprintErrorInfo(
					code='AUTHENTICATION_REQUIRED',
					message='BROWSER_USE_API_KEY environment variable not set',
					missing_parameters=None,
				),
			)

		try:
			client = await self._get_client()

			# Build request
			request_data = BlueprintExecutionRequest(
				blueprint_id=blueprint_id or f'{group}_{endpoint}',
				parameters=parameters,
				metadata=metadata,
			)

			# Execute blueprint
			path = f'/{group}/{endpoint}'
			logger.debug(f'📘 Executing blueprint: POST {path}')

			response = await client.post(path, json=request_data.model_dump(exclude_none=True))
			response.raise_for_status()

			# Parse response
			try:
				exec_response = BlueprintExecutionResponse.model_validate(response.json())
				if exec_response.success:
					logger.info(f'✅ Blueprint {group}_{endpoint} executed successfully')
				else:
					logger.warning(
						f'⚠️ Blueprint {group}_{endpoint} failed: {exec_response.error.message if exec_response.error else "Unknown error"}'
					)
				return exec_response
			except ValidationError as e:
				logger.error(f'Failed to parse blueprint execution response: {e}')
				return BlueprintExecutionResponse(
					success=False,
					data=None,
					error=BlueprintErrorInfo(
						code='INVALID_RESPONSE', message=f'Failed to parse response: {e}', missing_parameters=None
					),
				)

		except httpx.HTTPStatusError as e:
			error_msg = f'HTTP {e.response.status_code}'
			try:
				error_data = e.response.json()
				if 'error' in error_data:
					error_msg = error_data['error'].get('message', error_msg)
			except Exception:
				pass

			logger.error(f'Blueprint execution failed: {error_msg}')
			return BlueprintExecutionResponse(
				success=False,
				data=None,
				error=BlueprintErrorInfo(code='EXECUTION_ERROR', message=error_msg, missing_parameters=None),
			)
		except httpx.ConnectError:
			logger.error(f'Cannot connect to blueprint backend at {self.base_url}')
			return BlueprintExecutionResponse(
				success=False,
				data=None,
				error=BlueprintErrorInfo(
					code='BACKEND_UNAVAILABLE', message='Blueprint backend not reachable', missing_parameters=None
				),
			)
		except httpx.TimeoutException:
			logger.error(f'Blueprint execution timed out for {group}_{endpoint}')
			return BlueprintExecutionResponse(
				success=False,
				data=None,
				error=BlueprintErrorInfo(code='TIMEOUT', message='Blueprint execution timed out', missing_parameters=None),
			)
		except Exception as e:
			logger.error(f'Unexpected error executing blueprint: {type(e).__name__}: {e}')
			return BlueprintExecutionResponse(
				success=False,
				data=None,
				error=BlueprintErrorInfo(
					code='UNEXPECTED_ERROR', message=f'{type(e).__name__}: {str(e)}', missing_parameters=None
				),
			)

	async def __aenter__(self):
		"""Context manager entry."""
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Context manager exit - close client."""
		await self.close()
