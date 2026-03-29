"""
Inkbox tools for Browser Use agents.

Provides email, SMS, vault/credential, secure-fill, and QR-code actions
via an Inkbox AgentIdentity.
"""

import asyncio
import dataclasses
import itertools
import json
import logging
import re
import time
from typing import Any

import cv2  # type: ignore
import numpy as np  # type: ignore
from inkbox import APIKeyPayload, Inkbox, LoginPayload, OtherPayload
from inkbox.agent_identity import AgentIdentity
from inkbox.vault.totp import TOTPConfig, parse_totp_uri
from inkbox.vault.types import KeyPairPayload, SSHKeyPayload

from browser_use import Tools
from browser_use.browser import BrowserSession
from browser_use.browser.events import TypeTextEvent

logger = logging.getLogger(__name__)

DEFAULT_VAULT_KEY = 'Bu_Inkbox_Demo_Vault!2026'


# ── Vault setup ─────────────────────────────────────────────────────


def setup_vault(inkbox_client: Inkbox, vault_key: str | None = None) -> bool:
	"""Ensure the vault is created and unlocked. Returns True on success.

	Logic:
	  A) vault_key provided (e.g. from env var) → unlock with it
	  B) No vault exists → create one with the demo default key
	  C) Vault exists, no key provided → try default key, ask if it fails
	"""
	if not vault_key:
		# Check if a vault already exists for this org
		try:
			inkbox_client.vault.info()
			vault_exists = True
		except Exception:
			vault_exists = False

		if not vault_exists:
			# Scenario B: First run — create a vault with the demo default key
			print(f'No vault found — creating one with default key: "{DEFAULT_VAULT_KEY}"')
			try:
				result = inkbox_client.vault.initialize(DEFAULT_VAULT_KEY)
				print('Vault created! Save these recovery codes somewhere safe:')
				for i, code in enumerate(result.recovery_codes, 1):
					print(f'  {i}. {code}')
			except Exception as e:
				print(f'\nFailed to create vault: {e}')
				return False
			vault_key = DEFAULT_VAULT_KEY
		else:
			# Scenario C: Vault exists — try the default key silently
			try:
				inkbox_client.vault.unlock(DEFAULT_VAULT_KEY)
				return True
			except Exception:
				# Default key didn't work — ask the user
				vault_key = input('Vault found. Enter your vault key to unlock: ').strip()
				if not vault_key:
					print('No vault key provided. Exiting.')
					return False

	# Unlock (skips if already unlocked above)
	if not inkbox_client.vault._unlocked:
		try:
			inkbox_client.vault.unlock(vault_key)
		except Exception as e:
			print(f'\nFailed to unlock vault: {e}')
			print('Check that the vault key matches the one used to create it.')
			return False

	return True


# ── Private helpers ──────────────────────────────────────────────────


def _to_json(data: Any) -> str:
	"""Serialize SDK dataclasses (or lists of them) to a JSON string."""
	if isinstance(data, list):
		data = [dataclasses.asdict(d) if dataclasses.is_dataclass(d) and not isinstance(d, type) else d for d in data]
	elif dataclasses.is_dataclass(data) and not isinstance(data, type):
		data = dataclasses.asdict(data)
	return json.dumps(data, indent=2, default=str)


def _html_to_text(html: str) -> str:
	"""Strip tags/scripts/styles from HTML and return plain text."""
	html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<style\b[^>]*>.*?</style\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<[^>]+>', '', html)
	html = html.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<')
	html = html.replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
	return re.sub(r'\s+', ' ', html).strip()


def _parse_llm_json(raw: str) -> dict:
	"""Parse a JSON string, tolerating backslash-escaped quotes from LLMs."""
	cleaned = raw.replace('\\"', '"').replace("\\'", "'")
	try:
		return json.loads(cleaned)
	except json.JSONDecodeError:
		return json.loads(raw)


# ── TOTP / payload builders ─────────────────────────────────────────


def _dict_to_secret_payload(secret_type: str, data: dict) -> Any:
	"""Build a typed SDK payload from a *secret_type* string and dict."""
	if secret_type == 'login' and data.get('totp') is not None:
		data = dict(data)
		totp = data['totp']
		if isinstance(totp, str):
			data['totp'] = parse_totp_uri(totp)
		elif isinstance(totp, dict):
			uri = totp.get('uri')
			data['totp'] = parse_totp_uri(uri) if uri else TOTPConfig(**{k: v for k, v in totp.items() if v is not None})

	builders: dict[str, Any] = {
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


# ── InkboxTools ─────────────────────────────────────────────────────


class InkboxTools(Tools):
	"""Browser Use :class:`Tools` subclass backed by an Inkbox :class:`AgentIdentity`."""

	def __init__(
		self,
		identity: AgentIdentity,
		inkbox_client: Inkbox,
	):
		super().__init__()
		self.identity = identity
		self.inkbox_client = inkbox_client

		builtin_actions = set(self.registry.registry.actions.keys())
		self._register_email_tools()
		self._register_sms_tools()
		self._register_vault_tools()
		self._register_secure_fill_tools()
		self._register_qr_tools()
		self._inkbox_actions = set(self.registry.registry.actions.keys()) - builtin_actions

		self._print_identity_summary()

	def _print_identity_summary(self) -> None:
		"""Print a summary of the agent identity and available capabilities."""
		ident = self.identity
		email = ident.mailbox.email_address if ident.mailbox else '(none)'
		phone = ident.phone_number.number if ident.phone_number else '(none)'
		vault_ok = self.inkbox_client and self.inkbox_client.vault._unlocked is not None
		vault_status = 'unlocked' if vault_ok else 'locked / not configured'
		tools_count = len(self._inkbox_actions)

		print()
		print('┌──────────────────────────────────────────────────┐')
		print('│  Browser Use Inkbox Agent                        │')
		print('├──────────────────────────────────────────────────┤')
		print(f'│  Handle:  {ident.agent_handle:<39}│')
		print(f'│  ID:      {str(ident.id):<39}│')
		print(f'│  Email:   {email:<39}│')
		print(f'│  Phone:   {phone:<39}│')
		print(f'│  Vault:   {vault_status:<39}│')
		print(f'│  Tools:   {f"{tools_count} Inkbox tools registered":<39}│')
		print('└──────────────────────────────────────────────────┘')
		print()

	# ── Email tools ──────────────────────────────────────────────────

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
			'Use this to retrieve verification codes, confirmation links, or any expected incoming email.'
		)
		async def get_latest_email(max_wait_seconds: int = 30) -> str:
			deadline = time.time() + max_wait_seconds
			while True:
				emails = list(await asyncio.to_thread(lambda: list(itertools.islice(self.identity.iter_unread_emails(), 1))))
				if emails:
					msg = emails[0]
					await asyncio.to_thread(self.identity.mark_emails_read, [str(msg.id)])
					detail = await asyncio.to_thread(self.identity.get_message, str(msg.id))
					body = detail.body_text or ''
					if not body and detail.body_html:
						body = _html_to_text(detail.body_html)
					logger.info('Got email from %s: %s', msg.from_address, msg.subject)
					return f'From: {msg.from_address}\nSubject: {msg.subject}\nBody: {body}'
				if time.time() >= deadline:
					return f'No email received within {max_wait_seconds}s'
				await asyncio.sleep(2)

		@self.action('List recent emails in the inbox. Returns subject, sender, and ID for each.')
		async def list_emails(limit: int = 10) -> str:
			emails = await asyncio.to_thread(lambda: list(itertools.islice(self.identity.iter_emails(), limit)))
			if not emails:
				return 'No emails found.'
			return _to_json(emails)

		@self.action('Read the full body of a specific email by its message ID.')
		async def read_email(message_id: str) -> str:
			detail = await asyncio.to_thread(self.identity.get_message, message_id)
			return _to_json(detail)

	# ── SMS tools ────────────────────────────────────────────────────

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

	# ── Vault tools ──────────────────────────────────────────────────

	def _register_vault_tools(self) -> None:
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
			payload_obj = _dict_to_secret_payload(secret_type, _parse_llm_json(payload))
			secret = await asyncio.to_thread(
				self.identity.create_secret,
				name,
				payload_obj,
				description=description,
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
				kwargs['payload'] = _dict_to_secret_payload(secret_type, _parse_llm_json(payload))

			unlocked = self.inkbox_client.vault._unlocked  # type: ignore[union-attr]
			secret = await asyncio.to_thread(unlocked.update_secret, secret_id, **kwargs)
			return f'Credential updated. ID: {secret.id}, name: {secret.name}'

		@self.action('Generate a TOTP (2FA) code for a login credential. Returns the code and how many seconds until it expires.')
		async def get_totp_code(secret_id: str) -> str:
			code = await asyncio.to_thread(self.identity.get_totp_code, secret_id)
			return f'TOTP code: {code.code} (expires in {code.seconds_remaining}s)'

	# ── Secure fill tools ────────────────────────────────────────────

	def _register_secure_fill_tools(self) -> None:
		"""Tools that fill credentials directly into form fields without exposing secrets to the LLM."""
		try:
			self.identity.credentials
		except Exception:
			return

		async def _type_into_index(browser_session: BrowserSession, index: int, text: str) -> bool:
			"""Type *text* into the element at *index* via CDP (handles shadow DOM)."""
			node = await browser_session.get_element_by_index(index)
			if node is None:
				return False
			event = browser_session.event_bus.dispatch(
				TypeTextEvent(node=node, text=text, clear=True, is_sensitive=True, sensitive_key_name='credential')
			)
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)
			return True

		@self.action(
			'Fill a login credential into form fields by element index (the same numbers shown in the page state). '
			'The actual values are NEVER shown to the agent — they are injected directly into the page. '
			'Use this instead of get_credential + manual typing to keep secrets out of the conversation.'
		)
		async def fill_credential(
			browser_session: BrowserSession,
			secret_id: str,
			username_index: int | None = None,
			password_index: int | None = None,
			email_index: int | None = None,
		) -> str:
			cred = await asyncio.to_thread(self.identity.get_secret, secret_id)
			payload = cred.payload
			filled = []

			username = getattr(payload, 'username', None)
			if username_index is not None and username:
				if await _type_into_index(browser_session, username_index, username):
					filled.append('username')

			email = getattr(payload, 'email', None)
			if email_index is not None and email:
				if await _type_into_index(browser_session, email_index, email):
					filled.append('email')

			password = getattr(payload, 'password', None)
			if password_index is not None and password:
				if await _type_into_index(browser_session, password_index, password):
					filled.append('password')

			if not filled:
				return 'No fields were filled — check your element indices or credential payload.'
			logger.info('Securely filled %s for secret %s', ', '.join(filled), secret_id)
			return f'Securely filled: {", ".join(filled)} (values hidden from agent)'

		@self.action(
			'Generate a TOTP code and fill it directly into a form field by element index '
			'(the same numbers shown in the page state). '
			'The code is NEVER shown to the agent — it is injected directly into the page. '
			'Use this instead of get_totp_code + manual typing to keep 2FA codes out of the conversation.'
		)
		async def fill_totp_code(
			browser_session: BrowserSession,
			secret_id: str,
			index: int,
		) -> str:
			code = await asyncio.to_thread(self.identity.get_totp_code, secret_id)
			if not await _type_into_index(browser_session, index, str(code.code)):
				return f'Element index {index} not found — page may have changed.'
			logger.info('Securely filled TOTP code for secret %s', secret_id)
			return f'TOTP code filled (expires in {code.seconds_remaining}s). Value hidden from agent.'

	# ── QR code tools ────────────────────────────────────────────────

	def _register_qr_tools(self) -> None:
		@self.action(
			'Read QR codes from the current page. Takes a screenshot and decodes any QR codes found. '
			'Use this when you see a QR code on the page (e.g. for 2FA authenticator setup).'
		)
		async def read_qr_code(browser_session: BrowserSession) -> str:
			screenshot_bytes = await browser_session.take_screenshot(full_page=False)
			arr = np.frombuffer(screenshot_bytes, dtype=np.uint8)
			image = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # type: ignore[arg-type]
			detector = cv2.QRCodeDetector()
			ok, decoded, *_ = detector.detectAndDecodeMulti(image)  # type: ignore[misc]
			if not ok:
				decoded = ()
			decoded = [d for d in decoded if d]
			if not decoded:
				return 'No QR codes found on the current page.'
			logger.info('Decoded %d QR code(s)', len(decoded))
			if len(decoded) == 1:
				return f'QR code content: {decoded[0]}'
			return 'QR codes found:\n' + '\n'.join(f'  {i + 1}. {d}' for i, d in enumerate(decoded))
