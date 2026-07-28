"""Persistent WebSocket transport for the OpenAI Responses API."""

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import httpx
from openai.types.responses import Response, ResponseCompletedEvent, ResponseFailedEvent, ResponseIncompleteEvent
from pydantic import BaseModel, ConfigDict

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError


class ResponsesWebSocketErrorBody(BaseModel):
	"""Error body sent by the Responses WebSocket endpoint."""

	code: str | None = None
	message: str
	param: str | None = None
	type: str | None = None

	model_config = ConfigDict(extra='allow')


class ResponsesWebSocketErrorEvent(BaseModel):
	"""OpenAI's flat error frame, with nested Gateway errors also accepted."""

	type: Literal['error']
	code: str | None = None
	message: str | None = None
	param: str | None = None
	sequence_number: int | None = None
	status: int | None = None
	error: ResponsesWebSocketErrorBody | None = None

	model_config = ConfigDict(extra='allow')


@dataclass
class _ResponsesWebSocketSession:
	lock: asyncio.Lock = field(default_factory=asyncio.Lock)
	http_session: aiohttp.ClientSession | None = None
	websocket: aiohttp.ClientWebSocketResponse | None = None
	connected_at: float = 0.0
	model: str | None = None


class ResponsesWebSocketTransport:
	"""Manage one sequential Responses WebSocket connection per agent session."""

	_MAX_CONNECTION_AGE_SECONDS = 55 * 60

	def __init__(
		self,
		*,
		api_key: str | None,
		organization: str | None,
		project: str | None,
		base_url: str | httpx.URL | None,
		websocket_base_url: str | httpx.URL | None,
		timeout: float | httpx.Timeout | None,
		default_headers: Mapping[str, str] | None,
		default_query: Mapping[str, object] | None,
		model: str,
	):
		self.api_key = api_key
		self.organization = organization
		self.project = project
		self.url = self._responses_websocket_url(websocket_base_url or base_url)
		self.timeout = self._timeout_seconds(timeout)
		self.default_headers = dict(default_headers or {})
		self.default_query = {key: str(value) for key, value in (default_query or {}).items()}
		self.model = model
		self._sessions: dict[str, _ResponsesWebSocketSession] = {}

	@staticmethod
	def _timeout_seconds(timeout: float | httpx.Timeout | None) -> float:
		if isinstance(timeout, (int, float)):
			return float(timeout)
		if isinstance(timeout, httpx.Timeout):
			return float(timeout.read if timeout.read is not None else 600.0)
		return 600.0

	@staticmethod
	def _responses_websocket_url(base_url: str | httpx.URL | None) -> str:
		raw_url = str(base_url or 'https://api.openai.com/v1').rstrip('/')
		parts = urlsplit(raw_url)
		scheme = {'http': 'ws', 'https': 'wss'}.get(parts.scheme, parts.scheme)
		path = parts.path if parts.path.endswith('/responses') else f'{parts.path}/responses'
		return urlunsplit((scheme, parts.netloc, path, parts.query, parts.fragment))

	def _headers(self) -> dict[str, str]:
		headers = dict(self.default_headers)
		lower_names = {name.lower() for name in headers}
		if 'authorization' not in lower_names:
			if not self.api_key:
				raise ModelProviderError(
					message='The OPENAI_API_KEY environment variable or api_key parameter is required',
					status_code=401,
					model=self.model,
				)
			headers['Authorization'] = f'Bearer {self.api_key}'
		if self.organization and 'openai-organization' not in lower_names:
			headers['OpenAI-Organization'] = self.organization
		if self.project and 'openai-project' not in lower_names:
			headers['OpenAI-Project'] = self.project
		return headers

	async def _close_connection(self, session: _ResponsesWebSocketSession) -> None:
		if session.websocket is not None and not session.websocket.closed:
			await session.websocket.close()
		session.websocket = None
		if session.http_session is not None and not session.http_session.closed:
			await session.http_session.close()
		session.http_session = None
		session.connected_at = 0.0

	async def _ensure_connection(self, session: _ResponsesWebSocketSession) -> None:
		connection_expired = time.monotonic() - session.connected_at >= self._MAX_CONNECTION_AGE_SECONDS
		if session.websocket is not None and not session.websocket.closed and not connection_expired:
			return

		await self._close_connection(session)
		client_timeout = aiohttp.ClientTimeout(total=self.timeout)
		session.http_session = aiohttp.ClientSession(timeout=client_timeout)
		try:
			session.websocket = await session.http_session.ws_connect(
				self.url,
				headers=self._headers(),
				params=self.default_query,
				heartbeat=30.0,
				receive_timeout=self.timeout,
				max_msg_size=16 * 1024 * 1024,
			)
		except Exception:
			await self._close_connection(session)
			raise
		session.connected_at = time.monotonic()

	async def _receive_terminal_response(self, websocket: aiohttp.ClientWebSocketResponse) -> Response:
		while True:
			message = await websocket.receive()
			if message.type == aiohttp.WSMsgType.TEXT:
				try:
					payload = json.loads(message.data)
				except json.JSONDecodeError as exc:
					raise ModelProviderError(
						message=f'Invalid JSON frame from Responses WebSocket: {exc}',
						status_code=502,
						model=self.model,
					) from exc

				event_type = payload.get('type') if isinstance(payload, dict) else None
				if event_type == 'response.completed':
					return ResponseCompletedEvent.model_validate(payload).response
				if event_type == 'response.failed':
					return ResponseFailedEvent.model_validate(payload).response
				if event_type == 'response.incomplete':
					return ResponseIncompleteEvent.model_validate(payload).response
				if event_type == 'error':
					error_event = ResponsesWebSocketErrorEvent.model_validate(payload)
					error_code = error_event.error.code if error_event.error is not None else error_event.code
					error_type = error_event.error.type if error_event.error is not None else None
					error_message = (
						error_event.error.message
						if error_event.error is not None
						else error_event.message or 'OpenAI Responses WebSocket request failed'
					)
					if error_code == 'websocket_connection_limit_reached':
						raise ConnectionError(error_message)
					is_rate_limit = error_event.status == 429 or any(
						value is not None and 'rate_limit' in value for value in (error_code, error_type)
					)
					if is_rate_limit:
						raise ModelRateLimitError(message=error_message, model=self.model)
					raise ModelProviderError(
						message=error_message,
						status_code=error_event.status or 502,
						model=self.model,
					)
			elif message.type == aiohttp.WSMsgType.ERROR:
				raise ConnectionError(str(websocket.exception() or 'Responses WebSocket failed'))
			elif message.type == aiohttp.WSMsgType.BINARY:
				raise ModelProviderError(
					message='Unexpected binary frame from Responses WebSocket',
					status_code=502,
					model=self.model,
				)
			elif message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
				raise ConnectionError(f'Responses WebSocket closed before a terminal event (code={websocket.close_code})')

	async def send(
		self,
		*,
		session_key: str,
		request: dict[str, Any],
	) -> Response:
		"""Send one full-context request and return its terminal response."""
		session = self._sessions.setdefault(session_key, _ResponsesWebSocketSession())
		async with session.lock:
			request_model = str(request.get('model', ''))
			if session.model is not None and session.model != request_model:
				await self._close_connection(session)
			session.model = request_model
			try:
				await self._ensure_connection(session)
				assert session.websocket is not None
				await session.websocket.send_json({'type': 'response.create', **request})
				return await self._receive_terminal_response(session.websocket)
			except asyncio.CancelledError:
				await self._close_connection(session)
				raise
			except aiohttp.WSServerHandshakeError as exc:
				await self._close_connection(session)
				if exc.status == 429:
					raise ModelRateLimitError(message=str(exc), model=self.model) from exc
				if 400 <= exc.status < 500:
					raise ModelProviderError(message=str(exc), status_code=exc.status, model=self.model) from exc
				raise ConnectionError(str(exc)) from exc
			except (aiohttp.ClientError, TimeoutError, ConnectionError, asyncio.TimeoutError) as exc:
				await self._close_connection(session)
				raise ConnectionError(str(exc)) from exc
			except Exception:
				# A malformed or unexpected frame invalidates the one-in-flight stream.
				# Reconnect before allowing another request on this session.
				await self._close_connection(session)
				raise

	async def close_session(self, session_prefix: str) -> None:
		"""Close all invocation scopes belonging to one agent session."""
		matching_keys = [key for key in self._sessions if key == session_prefix or key.startswith(f'{session_prefix}:')]
		for key in matching_keys:
			session = self._sessions.pop(key)
			async with session.lock:
				await self._close_connection(session)

	async def close(self) -> None:
		"""Close every managed WebSocket session."""
		sessions = list(self._sessions.values())
		self._sessions.clear()
		for session in sessions:
			async with session.lock:
				await self._close_connection(session)
