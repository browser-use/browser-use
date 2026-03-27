"""
Inkbox tools for Browser Use agents.

Provides email, SMS, and vault/credential actions via an Inkbox AgentIdentity.
Install: pip install inkbox
API key: https://inkbox.ai/console
Docs: https://inkbox.ai/docs
"""

import asyncio
import dataclasses
import json
import logging
import re
import time
from typing import Any

from inkbox import Inkbox, LoginPayload, APIKeyPayload, OtherPayload  # type: ignore
from inkbox.agent_identity import AgentIdentity  # type: ignore
from inkbox.vault.types import KeyPairPayload, SSHKeyPayload  # type: ignore

from browser_use import Tools

if not logging.getLogger().handlers:
	logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

logger = logging.getLogger(__name__)


def _to_json(data: Any) -> str:
	"""Serialize SDK dataclasses (or lists of them) to a JSON string."""
	if isinstance(data, list):
		data = [dataclasses.asdict(d) if dataclasses.is_dataclass(d) else d for d in data]
	elif dataclasses.is_dataclass(data):
		data = dataclasses.asdict(data)
	return json.dumps(data, indent=2, default=str)


def _html_to_text(html: str) -> str:
	"""Simple HTML to plain text conversion."""
	html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<style\b[^>]*>.*?</style\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<[^>]+>', '', html)
	html = html.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<')
	html = html.replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
	html = re.sub(r'\s+', ' ', html).strip()
	return html


class InkboxTools(Tools):
	"""Browser Use tools backed by an Inkbox AgentIdentity."""

	def __init__(
		self,
		identity: AgentIdentity,
		inkbox_client: Inkbox | None = None,
	):
		super().__init__()
		self.identity = identity
		self.inkbox_client = inkbox_client

		self._register_email_tools()
		self._register_sms_tools()
		self._register_vault_tools()

	# ── Email tools ───────────────────────────────────────────────────

	def _register_email_tools(self) -> None:
		if not self.identity.mailbox:
			logger.info('No mailbox on identity — skipping email tools')
			return

		@self.action('Get the agent email address. Use this when a site asks for an email during signup or login.')
		async def get_email_address() -> str:
			assert self.identity.mailbox is not None
			addr = self.identity.mailbox.email_address
			logger.info('Email address: %s', addr)
			return addr

		@self.action(
			'Get the latest unread email. Polls for up to max_wait_seconds if none found yet. '
			'Use this to retrieve 2FA codes, confirmation links, or any expected incoming email.'
		)
		async def get_latest_email(max_wait_seconds: int = 30) -> str:
			deadline = time.time() + max_wait_seconds
			while True:
				emails = list(await asyncio.to_thread(lambda: list(_take(self.identity.iter_unread_emails(), 1))))
				if emails:
					msg = emails[0]
					await asyncio.to_thread(self.identity.mark_emails_read, [str(msg.id)])
					detail = await asyncio.to_thread(self.identity.get_message, str(msg.id))
					body = detail.body_text or ''
					if not body and detail.body_html:
						body = _html_to_text(detail.body_html)
					logger.info('Got email from %s: %s', msg.sender, msg.subject)
					return f'From: {msg.sender}\nSubject: {msg.subject}\nBody: {body}'
				if time.time() >= deadline:
					return f'No email received within {max_wait_seconds}s'
				await asyncio.sleep(2)

		@self.action('List recent emails in the inbox. Returns subject, sender, and ID for each.')
		async def list_emails(limit: int = 10) -> str:
			emails = await asyncio.to_thread(lambda: list(_take(self.identity.iter_emails(), limit)))
			if not emails:
				return 'No emails found.'
			return _to_json(emails)

		@self.action('Read the full body of a specific email by its message ID.')
		async def read_email(message_id: str) -> str:
			detail = await asyncio.to_thread(self.identity.get_message, message_id)
			return _to_json(detail)

	# ── SMS tools ─────────────────────────────────────────────────────

	def _register_sms_tools(self) -> None:
		if not self.identity.phone_number:
			logger.info('No phone number on identity — skipping SMS tools')
			return

		@self.action('Get the agent phone number. Use when a site asks for a phone number for SMS verification.')
		async def get_phone_number() -> str:
			assert self.identity.phone_number is not None
			number = self.identity.phone_number.number
			logger.info('Phone number: %s', number)
			return number

		@self.action(
			'Get the latest unread text message. Polls for up to max_wait_seconds if none found yet. '
			'Use this to retrieve SMS verification codes.'
		)
		async def get_latest_text(max_wait_seconds: int = 30) -> str:
			deadline = time.time() + max_wait_seconds
			while True:
				texts = await asyncio.to_thread(self.identity.list_texts, is_read=False, limit=1)
				if texts:
					txt = texts[0]
					await asyncio.to_thread(self.identity.mark_text_read, str(txt.id))
					logger.info('Got text from %s: %s', txt.remote_phone_number, txt.text)
					return f'From: {txt.remote_phone_number}\nBody: {txt.text}'
				if time.time() >= deadline:
					return f'No text message received within {max_wait_seconds}s'
				await asyncio.sleep(2)

		@self.action('List recent text messages.')
		async def list_texts(limit: int = 10) -> str:
			texts = await asyncio.to_thread(self.identity.list_texts, limit=limit)
			if not texts:
				return 'No text messages found.'
			return _to_json(texts)

	# ── Vault tools ───────────────────────────────────────────────────

	def _register_vault_tools(self) -> None:
		# Only register vault tools if the vault has been unlocked
		try:
			self.identity.credentials
		except Exception:
			logger.info('Vault not unlocked — skipping credential tools')
			return

		@self.action('List credentials (passwords, API keys, etc.) accessible to this agent identity.')
		async def list_credentials(secret_type: str | None = None) -> str:
			def _collect() -> list:
				creds = self.identity.credentials
				type_map = {
					'login': creds.list_logins,
					'api_key': creds.list_api_keys,
					'key_pair': creds.list_key_pairs,
					'ssh_key': creds.list_ssh_keys,
				}
				if secret_type:
					fn = type_map.get(secret_type)
					return list(fn()) if fn else []
				return list(creds.list())

			secrets = await asyncio.to_thread(_collect)
			if not secrets:
				return 'No credentials found.'
			return _to_json(secrets)

		@self.action('Get a specific credential from the vault by its secret ID.')
		async def get_credential(secret_id: str) -> str:
			secret = await asyncio.to_thread(self.identity.get_secret, secret_id)
			return _to_json(secret)

		@self.action(
			'Store a new credential in the vault. Supported secret types:\n'
			'- login: {"password": "...", "username": "...", "email": "...", "url": "...", "totp": {"uri": "otpauth://..."}}\n'
			'- api_key: {"api_key": "...", "endpoint": "..."}\n'
			'- key_pair: {"access_key": "...", "secret_key": "...", "endpoint": "..."}\n'
			'- other: {"data": "..."}\n'
			'Only password (login) / api_key / access_key+secret_key / data are required; the rest are optional.'
		)
		async def store_credential(name: str, secret_type: str, payload: str, description: str | None = None) -> str:
			payload_dict = json.loads(payload)
			payload_obj = _build_payload(secret_type, payload_dict)
			secret = await asyncio.to_thread(
				self.identity.create_secret, name, payload_obj, description=description,
			)
			return f'Credential stored. ID: {secret.id}, name: {secret.name}, type: {secret_type}'

		@self.action(
			'Update an existing credential in the vault. Pass the secret_id, and optionally '
			'a new name, description, or payload (same JSON format as store_credential, same secret_type as the original).'
		)
		async def update_credential(
			secret_id: str,
			name: str | None = None,
			description: str | None = None,
			payload: str | None = None,
			secret_type: str | None = None,
		) -> str:
			kwargs: dict[str, Any] = {}
			if name is not None:
				kwargs['name'] = name
			if description is not None:
				kwargs['description'] = description
			if payload is not None:
				if not secret_type:
					return 'Error: secret_type is required when updating payload'
				kwargs['payload'] = _build_payload(secret_type, json.loads(payload))

			unlocked = self.inkbox_client.vault._unlocked  # type: ignore
			secret = await asyncio.to_thread(unlocked.update_secret, secret_id, **kwargs)
			return f'Credential updated. ID: {secret.id}, name: {secret.name}'

		@self.action(
			'Generate a TOTP (2FA) code for a login credential. '
			'Returns the code and how many seconds until it expires.'
		)
		async def get_totp_code(secret_id: str) -> str:
			code = await asyncio.to_thread(self.identity.get_totp_code, secret_id)
			totp_code = str(code.code)
			seconds_remaining = code.seconds_remaining
			return f'TOTP code: {totp_code} (expires in {seconds_remaining}s). Enter this EXACT code: {totp_code}'


def _build_payload(secret_type: str, data: dict) -> Any:
	"""Build a typed SDK payload from a secret_type string and dict."""
	builders = {
		'login': lambda d: LoginPayload(**{k: v for k, v in d.items() if v is not None}),
		'api_key': lambda d: APIKeyPayload(**{k: v for k, v in d.items() if v is not None}),
		'key_pair': lambda d: KeyPairPayload(**{k: v for k, v in d.items() if v is not None}),
		'ssh_key': lambda d: SSHKeyPayload(**{k: v for k, v in d.items() if v is not None}),
		'other': lambda d: OtherPayload(**{k: v for k, v in d.items() if v is not None}),
	}
	builder = builders.get(secret_type)
	if not builder:
		raise ValueError(f'Unknown secret_type: {secret_type}. Use: {", ".join(builders)}')
	return builder(data)


def _take(iterator: Any, n: int) -> list:
	"""Take up to n items from an iterator."""
	results = []
	for item in iterator:
		results.append(item)
		if len(results) >= n:
			break
	return results
