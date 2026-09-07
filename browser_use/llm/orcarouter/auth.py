"""Local PKCE authentication for OrcaRouter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import tempfile
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, field_validator

from browser_use.config import CONFIG, DBStyleConfigJSON, LLMEntry, create_default_config

DEFAULT_ORCAROUTER_AUTH_BASE_URL = 'https://www.orcarouter.ai'
DEFAULT_ORCAROUTER_API_BASE_URL = 'https://api.orcarouter.ai/v1'
DEFAULT_ORCAROUTER_APP_NAME = 'Browser Use'


class OrcaRouterAuthError(RuntimeError):
	"""An OrcaRouter authorization or credential-storage failure."""


def _validate_api_key(key: str) -> str:
	if not key.startswith('sk-orca-') or len(key) <= len('sk-orca-'):
		raise ValueError('OrcaRouter returned an invalid API key')
	if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in key):
		raise ValueError('OrcaRouter returned an invalid API key')
	return key


class OrcaRouterCredential(BaseModel):
	"""A durable API key minted by OrcaRouter's PKCE flow."""

	model_config = ConfigDict(frozen=True)

	api_key: str
	user_id: str
	scope: str = 'api'
	authorized_at: datetime
	generation: str
	needs_reauth: bool = False

	_validate_key = field_validator('api_key')(_validate_api_key)


class _OrcaRouterExchangeResponse(BaseModel):
	key: str
	user_id: str
	scope: str

	_validate_key = field_validator('key')(_validate_api_key)


class OrcaRouterCredentialStore:
	"""Read and atomically update OrcaRouter PKCE data in Browser Use's LLM config."""

	def __init__(self, path: Path | None = None):
		self.path = path or CONFIG._get_config_path()

	def load(self) -> OrcaRouterCredential | None:
		if not self.path.exists():
			return None
		try:
			config = DBStyleConfigJSON.model_validate_json(self.path.read_text())
			entry = next(
				(
					candidate
					for candidate in config.llm.values()
					if candidate.provider == 'orcarouter' and candidate.auth_method == 'pkce'
				),
				None,
			)
			if entry is None or not all(
				(entry.api_key, entry.user_id, entry.scope, entry.authorized_at, entry.credential_generation)
			):
				return None
			return OrcaRouterCredential.model_validate(
				{
					'api_key': entry.api_key,
					'user_id': entry.user_id,
					'scope': entry.scope,
					'authorized_at': entry.authorized_at,
					'generation': entry.credential_generation,
					'needs_reauth': entry.needs_reauth,
				}
			)
		except Exception as exc:
			raise OrcaRouterAuthError(f'Could not read the OrcaRouter credential at {self.path}') from exc

	def save(self, *, key: str, user_id: str) -> OrcaRouterCredential:
		credential = OrcaRouterCredential(
			api_key=key,
			user_id=user_id,
			scope='api',
			authorized_at=datetime.now(UTC),
			generation=str(uuid4()),
		)
		self._write(credential)
		return credential

	def mark_needs_reauth(self, generation: str) -> bool:
		credential = self.load()
		if credential is None or credential.generation != generation:
			return False
		self._write(credential.model_copy(update={'needs_reauth': True}))
		return True

	def clear(self) -> bool:
		config = self._load_config()
		entry_ids = [
			entry_id for entry_id, entry in config.llm.items() if entry.provider == 'orcarouter' and entry.auth_method == 'pkce'
		]
		if not entry_ids:
			return False
		for entry_id in entry_ids:
			del config.llm[entry_id]
		self._write_config(config)
		return True

	def _write(self, credential: OrcaRouterCredential) -> None:
		config = self._load_config()
		entry_id = next(
			(
				candidate_id
				for candidate_id, candidate in config.llm.items()
				if candidate.provider == 'orcarouter' and candidate.auth_method == 'pkce'
			),
			str(uuid4()),
		)
		previous = config.llm.get(entry_id)
		config.llm[entry_id] = LLMEntry(
			id=entry_id,
			default=previous.default if previous else False,
			created_at=previous.created_at if previous else datetime.now(UTC).isoformat(),
			api_key=credential.api_key,
			model=previous.model if previous else 'orcarouter/auto',
			provider='orcarouter',
			auth_method='pkce',
			user_id=credential.user_id,
			scope=credential.scope,
			authorized_at=credential.authorized_at.isoformat(),
			credential_generation=credential.generation,
			needs_reauth=credential.needs_reauth,
		)
		self._write_config(config)

	def _load_config(self) -> DBStyleConfigJSON:
		if not self.path.exists():
			return create_default_config()
		try:
			return DBStyleConfigJSON.model_validate_json(self.path.read_text())
		except Exception as exc:
			raise OrcaRouterAuthError(f'Could not read Browser Use configuration at {self.path}') from exc

	def _write_config(self, config: DBStyleConfigJSON) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		fd, temporary_name = tempfile.mkstemp(prefix=f'.{self.path.name}.', dir=self.path.parent)
		temporary_path = Path(temporary_name)
		try:
			os.chmod(temporary_path, 0o600)
			with os.fdopen(fd, 'w') as file:
				json.dump(config.model_dump(mode='json'), file, indent=2)
				file.write('\n')
				file.flush()
				os.fsync(file.fileno())
			os.replace(temporary_path, self.path)
			os.chmod(self.path, 0o600)
		except Exception:
			try:
				os.close(fd)
			except OSError:
				pass
			temporary_path.unlink(missing_ok=True)
			raise


def _is_loopback_host(host: str | None) -> bool:
	if host == 'localhost':
		return True
	if host is None:
		return False
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False


def _validated_auth_base_url(value: str) -> str:
	parsed = urlsplit(value)
	try:
		parsed.port
	except ValueError as exc:
		raise OrcaRouterAuthError('OrcaRouter auth base URL contains an invalid port') from exc
	if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
		raise OrcaRouterAuthError('OrcaRouter auth base URL must be an origin without credentials, query, or fragment')
	if parsed.path not in {'', '/'}:
		raise OrcaRouterAuthError('OrcaRouter auth base URL must not contain a path')
	if parsed.scheme != 'https' and not (parsed.scheme == 'http' and _is_loopback_host(parsed.hostname)):
		raise OrcaRouterAuthError('OrcaRouter auth base URL must use HTTPS (HTTP is allowed only for loopback testing)')
	return urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))


def resolve_orcarouter_auth_base_url(explicit: str | None = None) -> str:
	"""Resolve split and shared self-hosted endpoint overrides."""

	value = (
		explicit
		or os.getenv('ORCAROUTER_AUTH_BASE_URL')
		or os.getenv('ORCA_AUTH_BASE_URL')
		or os.getenv('ORCAROUTER_BASE_URL')
		or os.getenv('ORCA_BASE_URL')
		or DEFAULT_ORCAROUTER_AUTH_BASE_URL
	)
	return _validated_auth_base_url(value)


def resolve_orcarouter_api_base_url() -> str:
	"""Resolve the OpenAI-compatible API base without deriving it from the auth origin."""

	explicit = os.getenv('ORCAROUTER_API_BASE_URL') or os.getenv('ORCA_API_BASE_URL')
	shared = os.getenv('ORCAROUTER_BASE_URL') or os.getenv('ORCA_BASE_URL')
	value = explicit or shared or DEFAULT_ORCAROUTER_API_BASE_URL
	return validate_orcarouter_api_base_url(value, append_version_if_origin=True)


def validate_orcarouter_api_base_url(value: str | httpx.URL, *, append_version_if_origin: bool = False) -> str:
	parsed = urlsplit(str(value))
	try:
		parsed.port
	except ValueError as exc:
		raise OrcaRouterAuthError('OrcaRouter API base URL contains an invalid port') from exc
	if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
		raise OrcaRouterAuthError('OrcaRouter API base URL must not contain credentials, query, or fragment')
	if parsed.scheme != 'https' and not (parsed.scheme == 'http' and _is_loopback_host(parsed.hostname)):
		raise OrcaRouterAuthError('OrcaRouter API base URL must use HTTPS (HTTP is allowed only for loopback testing)')
	path = parsed.path.rstrip('/')
	if not path and append_version_if_origin:
		path = '/v1'
	return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def _pkce_verifier() -> str:
	# token_urlsafe(64) is URL-safe and produces an 86-character verifier (RFC 7636 permits 43-128).
	return secrets.token_urlsafe(64)


def _pkce_challenge(verifier: str) -> str:
	return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _html_response(status: int, title: str, message: str) -> bytes:
	body = (
		'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
		f'<title>{title}</title></head><body><main><h1>{title}</h1><p>{message}</p></main></body></html>'
	).encode()
	reason = {200: 'OK', 400: 'Bad Request', 404: 'Not Found', 409: 'Conflict'}.get(status, 'Error')
	headers = (
		f'HTTP/1.1 {status} {reason}\r\n'
		f'Content-Length: {len(body)}\r\n'
		'Content-Type: text/html; charset=utf-8\r\n'
		'Cache-Control: no-store\r\n'
		"Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'\r\n"
		'Connection: close\r\n\r\n'
	).encode()
	return headers + body


class OrcaRouterPKCEClient:
	"""Run OrcaRouter's authorization-code + PKCE flow on a loopback callback."""

	def __init__(
		self,
		*,
		auth_base_url: str | None = None,
		credential_store: OrcaRouterCredentialStore | None = None,
		http_client: httpx.AsyncClient | None = None,
		app_name: str = DEFAULT_ORCAROUTER_APP_NAME,
	):
		self.auth_base_url = resolve_orcarouter_auth_base_url(auth_base_url)
		self.credential_store = credential_store or OrcaRouterCredentialStore()
		self.http_client = http_client
		self.app_name = app_name

	async def login(
		self,
		*,
		open_browser: bool = True,
		on_authorization_url: Callable[[str], None] | None = None,
		timeout: float = 300,
	) -> OrcaRouterCredential:
		verifier = _pkce_verifier()
		challenge = _pkce_challenge(verifier)
		state = secrets.token_urlsafe(32)
		loop = asyncio.get_running_loop()
		callback_result: asyncio.Future[str] = loop.create_future()

		async def handle_callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
			try:
				request_line = (await asyncio.wait_for(reader.readline(), timeout=5)).decode('ascii', errors='replace')
				parts = request_line.rstrip('\r\n').split(' ')
				if len(parts) != 3 or parts[0] != 'GET':
					writer.write(_html_response(400, 'Invalid request', 'Return to the terminal and try again.'))
					return
				parsed = urlsplit(parts[1])
				if parsed.path != '/cb':
					writer.write(_html_response(404, 'Not found', 'Return to the terminal and try again.'))
					return
				query = parse_qs(parsed.query)
				returned_state = query.get('state', [''])[0]
				if not hmac.compare_digest(returned_state, state):
					writer.write(_html_response(400, 'Invalid state', 'The authorization response did not match this login.'))
					return
				if callback_result.done():
					writer.write(_html_response(409, 'Already handled', 'This authorization response was already handled.'))
					return
				if query.get('error', [''])[0]:
					callback_result.set_exception(OrcaRouterAuthError('OrcaRouter authorization was denied'))
					writer.write(_html_response(400, 'Authorization denied', 'Return to the terminal to try again.'))
					return
				code = query.get('code', [''])[0]
				if not code:
					callback_result.set_exception(
						OrcaRouterAuthError('OrcaRouter callback did not include an authorization code')
					)
					writer.write(_html_response(400, 'Missing code', 'Return to the terminal and try again.'))
					return
				callback_result.set_result(code)
				writer.write(_html_response(200, 'OrcaRouter connected', 'You can close this tab and return to Browser Use.'))
			except (TimeoutError, UnicodeError):
				writer.write(_html_response(400, 'Invalid request', 'Return to the terminal and try again.'))
			finally:
				with suppress(ConnectionError):
					await writer.drain()
				writer.close()
				with suppress(ConnectionError):
					await writer.wait_closed()

		server = await asyncio.start_server(handle_callback, host='127.0.0.1', port=0)
		socket = server.sockets[0]
		port = socket.getsockname()[1]
		callback_url = f'http://127.0.0.1:{port}/cb'
		authorization_query = urlencode(
			{
				'callback_url': callback_url,
				'code_challenge': challenge,
				'code_challenge_method': 'S256',
				'state': state,
				'app_name': self.app_name,
				'scope': 'api',
			}
		)
		authorization_url = f'{self.auth_base_url}/auth?{authorization_query}'

		try:
			if on_authorization_url is not None:
				on_authorization_url(authorization_url)
			if open_browser:
				await asyncio.to_thread(webbrowser.open, authorization_url)
			try:
				code = await asyncio.wait_for(callback_result, timeout=timeout)
			except TimeoutError as exc:
				raise OrcaRouterAuthError('Timed out waiting for OrcaRouter authorization') from exc
		finally:
			server.close()
			await server.wait_closed()

		response = await self._exchange(code=code, verifier=verifier)
		if response.scope != 'api':
			raise OrcaRouterAuthError(f'OrcaRouter granted scope {response.scope!r}; expected api')
		return self.credential_store.save(key=response.key, user_id=response.user_id)

	async def _exchange(self, *, code: str, verifier: str) -> _OrcaRouterExchangeResponse:
		payload = {
			'code': code,
			'code_verifier': verifier,
			'code_challenge_method': 'S256',
		}
		try:
			if self.http_client is not None:
				response = await self.http_client.post(f'{self.auth_base_url}/api/v1/auth/keys', json=payload)
			else:
				async with httpx.AsyncClient(timeout=30) as client:
					response = await client.post(f'{self.auth_base_url}/api/v1/auth/keys', json=payload)
		except httpx.HTTPError as exc:
			raise OrcaRouterAuthError('Could not reach the OrcaRouter key exchange endpoint') from exc

		if response.status_code < 200 or response.status_code >= 300:
			raise OrcaRouterAuthError(f'OrcaRouter key exchange failed (HTTP {response.status_code})')
		try:
			return _OrcaRouterExchangeResponse.model_validate(response.json())
		except Exception as exc:
			raise OrcaRouterAuthError('OrcaRouter key exchange returned an invalid response') from exc
