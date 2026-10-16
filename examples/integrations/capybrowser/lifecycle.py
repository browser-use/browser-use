"""Small, durable lifecycle for this example's single temporary Session."""

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

BASE = 'https://capybrowser.app.baizhi.cloud'
BODY = {'purpose': 'agent', 'max_seconds': 180}


class SafeError(Exception):
	"""Only constant, credential-free messages may cross the CLI boundary."""


class ApiResponse(BaseModel):
	status_code: int
	data: dict


class Billing(BaseModel):
	model_config = ConfigDict(strict=True)
	status: Literal['preparing', 'reserved', 'settling', 'settlement_pending', 'settled', 'waived', 'review_required']
	actual_charge_centipoints: int | None = None
	charge_stop_at: datetime | None = None


class Session(BaseModel):
	model_config = ConfigDict(strict=True)
	session_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,128}$')
	status: Literal['starting', 'ready', 'stopping', 'ending_review_required', 'released', 'failed']
	profile_id: None
	purpose: Literal['agent']
	max_seconds: Literal[180]
	expires_at: datetime
	ended_at: datetime | None = None
	billing: Billing


class Intent(BaseModel):
	model_config = ConfigDict(extra='forbid')
	schema_version: Literal[1, 2] = 2
	endpoint: Literal['https://capybrowser.app.baizhi.cloud'] = BASE
	credential_fingerprint: str
	idempotency_key: str = Field(pattern=r'^[a-f0-9]{32}$')
	body: dict[str, str | int]
	session_id: str | None = None
	delete_accepted: bool = False
	delete_attempted: bool = False
	delete_http_status: Literal[200, 202] | None = None
	last_observation: Session | None = None


class State:
	"""One private directory per run; retain it until recovery is complete."""

	def __init__(self, directory: Path, key: str, recover: bool):
		self.directory = directory
		fingerprint = hashlib.sha256(key.encode()).hexdigest()
		if not recover:
			directory.mkdir(mode=0o700, parents=False, exist_ok=False)
		# Advisory lock only for this one example, released automatically on process exit.
		import fcntl

		self.lock = (directory / 'lock').open('a')
		try:
			fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
			if recover:
				self.intent = Intent.model_validate_json((directory / 'intent.json').read_text())
				if self.intent.credential_fingerprint != fingerprint or self.intent.body != BODY:
					raise SafeError('Recovery requires the original credential and unchanged creation intent.')
				if self.intent.schema_version == 1:
					# Old state conflated 200 and 202; it cannot prove acceptance.
					self.intent.schema_version = 2
					self.intent.delete_accepted = False
					self.intent.delete_http_status = None
					self.save()
			else:
				self.intent = Intent(credential_fingerprint=fingerprint, idempotency_key=uuid.uuid4().hex, body=BODY)
				self.save()  # Must reach durable storage BEFORE the first HTTP request.
		except BaseException:
			self.lock.close()
			raise

	def save(self):
		tmp = self.directory / 'intent.tmp'
		with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
			stream.write(self.intent.model_dump_json(indent=2))
			stream.flush()
			os.fsync(stream.fileno())
		os.replace(tmp, self.directory / 'intent.json')
		fd = os.open(self.directory, os.O_RDONLY)
		try:
			os.fsync(fd)
		finally:
			os.close(fd)

	def close(self):
		self.lock.close()


class Lifecycle:
	def __init__(self, client: httpx.AsyncClient, state: State, poll: float = 1):
		self.client, self.state, self.poll = client, state, poll
		self.latest: Session | None = None

	async def request(self, method: str, path: str, **kwargs) -> ApiResponse:
		try:
			async with asyncio.timeout(10):
				response = await self.client.request(method, '/openapi/v1/browser/sessions' + path, **kwargs)
				accepted = (202,) if method == 'POST' and not path else (200, 202) if method == 'DELETE' else (200,)
				if response.status_code not in accepted:
					raise SafeError(f'Management API returned HTTP {response.status_code}; retain the saved intent.')
				value = response.json()
				if value.get('code') != 'ok' or not isinstance(value.get('data'), dict):
					raise SafeError('Invalid management response; retain the saved intent.')
				return ApiResponse(status_code=response.status_code, data=value['data'])
		except SafeError:
			raise
		except Exception:
			raise SafeError('Management request outcome is unknown; retain the saved intent.') from None

	def observe(self, data: dict) -> Session:
		try:
			session = Session.model_validate_json(json.dumps(data))
			if session.expires_at.tzinfo is None:
				raise ValueError()
			if self.state.intent.session_id not in (None, session.session_id):
				raise ValueError()
		except Exception:
			raise SafeError('Session identity or response contract did not match; retain the saved intent.') from None
		self.state.intent.session_id = session.session_id
		self.state.intent.last_observation = session
		self.latest = session
		self.state.save()
		return session

	@property
	def path(self):
		if not self.state.intent.session_id:
			raise SafeError('No verified Session ID; recover using the saved creation intent.')
		return '/' + quote(self.state.intent.session_id, safe='')

	async def create(self):
		response = await self.request(
			'POST', '', json=self.state.intent.body, headers={'Idempotency-Key': self.state.intent.idempotency_key}
		)
		self.observe(response.data)

	async def ready(self, timeout: float = 45) -> Session:
		async with asyncio.timeout(timeout):
			while True:
				session = self.observe((await self.request('GET', self.path)).data)
				if session.status == 'ready':
					return session
				if session.status != 'starting':
					raise SafeError('Session did not reach ready; ending the owned Session.')
				await asyncio.sleep(self.poll)

	async def control(self) -> str:
		from urllib.parse import urlsplit

		data = (await self.request('POST', self.path + '/control', json={})).data
		try:
			url = data['cdp_url']
			parts = urlsplit(url)
			expires = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
			if parts.scheme != 'wss' or not parts.hostname or parts.username or parts.password or parts.fragment:
				raise ValueError()
			if expires <= datetime.now(timezone.utc):
				raise ValueError()
			return url
		except Exception:
			raise SafeError('Invalid or expired control grant; ending the owned Session.') from None

	async def finish(self, timeout: float = 30) -> dict:
		"""DELETE acceptance, release and billing are independent facts."""
		self.latest = None  # Do not represent a saved/stale projection as a fresh check.
		try:
			async with asyncio.timeout(timeout):
				if not self.state.intent.session_id:
					return self.report()
				try:
					self.observe((await self.request('GET', self.path)).data)
				except SafeError:
					pass
				if self.latest is None or self.latest.status != 'released':
					try:
						self.state.intent.delete_attempted = True
						self.state.intent.delete_http_status = None
						self.state.save()
						response = await self.request('DELETE', self.path)
						self.observe(response.data)
						self.state.intent.delete_http_status = 202 if response.status_code == 202 else 200
						if response.status_code == 202:
							self.state.intent.delete_accepted = True
						self.state.save()
					except SafeError:
						pass
				while not self.complete():
					await asyncio.sleep(self.poll)
					try:
						self.observe((await self.request('GET', self.path)).data)
					except SafeError:
						continue
		except TimeoutError:
			pass
		return self.report()

	def complete(self):
		# Public failed is a terminal startup failure, not a confirmed release.
		# Final billing resolves cleanup; pending/review billing still needs recovery.
		return bool(
			self.latest and self.latest.status in ('released', 'failed') and self.latest.billing.status in ('settled', 'waived')
		)

	def report(self):
		session = self.latest
		billing = session.billing if session else None
		return {
			'session_id': self.state.intent.session_id,
			'delete_accepted': self.state.intent.delete_accepted,
			'delete_http_status': self.state.intent.delete_http_status,
			'delete_outcome': 'accepted'
			if self.state.intent.delete_http_status == 202
			else 'already_terminal'
			if self.state.intent.delete_http_status == 200
			else 'unknown'
			if self.state.intent.delete_attempted
			else 'not_requested',
			'session_status': session.status if session else 'unknown',
			'released': session.status == 'released' if session else None,
			'resource_outcome': 'unknown'
			if session is None
			else 'released'
			if session.status == 'released'
			else 'startup_failed'
			if session.status == 'failed'
			else 'unconfirmed',
			'billing_status': billing.status if billing else 'unknown',
			'actual_charge_centipoints': billing.actual_charge_centipoints
			if billing and billing.status in ('settled', 'waived')
			else None,
			'charge_stop_at': billing.charge_stop_at.isoformat() if billing and billing.charge_stop_at else None,
			'complete': self.complete(),
			'next_action': None
			if self.complete()
			else 'Run recover with the SAME state directory and original credential; do not start a replacement run.',
		}
