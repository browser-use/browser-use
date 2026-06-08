"""
Gmail API Service for Browser Use
Handles Gmail API authentication, email reading, and 2FA code extraction.
This service provides a clean interface for agents to interact with Gmail.
"""

import base64
import binascii
import logging
import os
from pathlib import Path
from typing import Any

import anyio
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from browser_use.config import CONFIG

logger = logging.getLogger(__name__)


class GmailService:
	"""
	Gmail API service for email reading.
	Provides functionality to:
	- Authenticate with Gmail API using OAuth2
	- Read recent emails with filtering
	- Return full email content for agent analysis
	"""

	# Gmail API scopes
	SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

	def __init__(
		self,
		credentials_file: str | None = None,
		token_file: str | None = None,
		config_dir: str | None = None,
		access_token: str | None = None,
	):
		"""
		Initialize Gmail Service
		Args:
		    credentials_file: Path to OAuth credentials JSON from Google Cloud Console
		    token_file: Path to store/load access tokens
		    config_dir: Directory to store config files (defaults to browser-use config directory)
		    access_token: Direct access token (skips file-based auth if provided)
		"""
		# Set up configuration directory using browser-use's config system
		if config_dir is None:
			self.config_dir = CONFIG.BROWSER_USE_CONFIG_DIR
		else:
			self.config_dir = Path(config_dir).expanduser().resolve()

		# Ensure config directory exists (only if not using direct token)
		if access_token is None:
			self.config_dir.mkdir(parents=True, exist_ok=True)

		# Set up credential paths
		self.credentials_file = credentials_file or self.config_dir / 'gmail_credentials.json'
		self.token_file = token_file or self.config_dir / 'gmail_token.json'

		# Direct access token support
		self.access_token = access_token

		self.service = None
		self.creds = None
		self._authenticated = False

	def is_authenticated(self) -> bool:
		"""Check if Gmail service is authenticated"""
		return self._authenticated and self.service is not None

	async def authenticate(self) -> bool:
		"""
		Handle OAuth authentication and token management
		Returns:
		    bool: True if authentication successful, False otherwise
		"""
		try:
			logger.info('🔐 Authenticating with Gmail API...')

			# Check if using direct access token
			if self.access_token:
				logger.info('🔑 Using provided access token')
				# Create credentials from access token
				self.creds = Credentials(token=self.access_token, scopes=self.SCOPES)
				# Test token validity by building service
				self.service = build('gmail', 'v1', credentials=self.creds)
				self._authenticated = True
				logger.info('✅ Gmail API ready with access token!')
				return True

			# Original file-based authentication flow
			# Try to load existing tokens
			if os.path.exists(self.token_file):
				self.creds = Credentials.from_authorized_user_file(str(self.token_file), self.SCOPES)
				logger.debug('📁 Loaded existing tokens')

			# If no valid credentials, run OAuth flow
			if not self.creds or not self.creds.valid:
				if self.creds and self.creds.expired and self.creds.refresh_token:
					logger.info('🔄 Refreshing expired tokens...')
					self.creds.refresh(Request())
				else:
					logger.info('🌐 Starting OAuth flow...')
					if not os.path.exists(self.credentials_file):
						logger.error(
							f'❌ Gmail credentials file not found: {self.credentials_file}\n'
							'Please download it from Google Cloud Console:\n'
							'1. Go to https://console.cloud.google.com/\n'
							'2. APIs & Services > Credentials\n'
							'3. Download OAuth 2.0 Client JSON\n'
							f"4. Save as 'gmail_credentials.json' in {self.config_dir}/"
						)
						return False

					flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), self.SCOPES)
					# Use specific redirect URI to match OAuth credentials
					self.creds = flow.run_local_server(port=8080, open_browser=True)

				# Save tokens for next time
				await anyio.Path(self.token_file).write_text(self.creds.to_json())
				logger.info(f'💾 Tokens saved to {self.token_file}')

			# Build Gmail service
			self.service = build('gmail', 'v1', credentials=self.creds)
			self._authenticated = True
			logger.info('✅ Gmail API ready!')
			return True

		except Exception as e:
			logger.error(f'❌ Gmail authentication failed: {e}')
			return False

	async def get_recent_emails(self, max_results: int = 10, query: str = '', time_filter: str = '1h') -> list[dict[str, Any]]:
		"""
		Get recent emails with optional query filter
		Args:
		    max_results: Maximum number of emails to fetch
		    query: Gmail search query (e.g., 'from:noreply@example.com')
		    time_filter: Time filter (e.g., '5m', '1h', '1d')
		Returns:
		    List of email dictionaries with parsed content
		"""
		if not self.is_authenticated():
			logger.error('❌ Gmail service not authenticated. Call authenticate() first.')
			return []

		try:
			# Add time filter to query if provided
			if time_filter and 'newer_than:' not in query:
				query = f'newer_than:{time_filter} {query}'.strip()

			logger.info(f'📧 Fetching {max_results} recent emails...')
			if query:
				logger.debug(f'🔍 Query: {query}')

			# Get message list
			assert self.service is not None
			results = self.service.users().messages().list(userId='me', maxResults=max_results, q=query).execute()

			messages = results.get('messages', [])
			if not messages:
				logger.info('📭 No messages found')
				return []

			logger.info(f'📨 Found {len(messages)} messages, fetching details...')

			# Get full message details
			emails = []
			for i, message in enumerate(messages, 1):
				logger.debug(f'📖 Reading email {i}/{len(messages)}...')

				full_message = self.service.users().messages().get(userId='me', id=message['id'], format='full').execute()

				email_data = self._parse_email(full_message)
				emails.append(email_data)

			return emails

		except HttpError as error:
			logger.error(f'❌ Gmail API error: {error}')
			return []
		except Exception as e:
			logger.error(f'❌ Unexpected error fetching emails: {e}')
			return []

	def _parse_email(self, message: dict[str, Any]) -> dict[str, Any]:
		"""Parse Gmail message into readable format"""
		headers = {h['name']: h['value'] for h in message['payload']['headers']}

		return {
			'id': message['id'],
			'thread_id': message['threadId'],
			'subject': headers.get('Subject', ''),
			'from': headers.get('From', ''),
			'to': headers.get('To', ''),
			'date': headers.get('Date', ''),
			'timestamp': int(message['internalDate']),
			'body': self._extract_body(message['payload']),
			'raw_message': message,
		}

	@staticmethod
	def _decode_part_data(data: str | None) -> str | None:
		"""Best-effort base64url -> utf-8 decode; returns ``None`` on missing/malformed data."""
		if not data:
			return None
		try:
			return base64.urlsafe_b64decode(data).decode('utf-8')
		except (binascii.Error, ValueError, UnicodeDecodeError):
			return None

	def _extract_body(self, payload: dict[str, Any]) -> str:
		"""Extract the email body, recursing into nested ``multipart/*`` containers.

		Gmail nests the actual text leaves inside intermediate ``multipart/*`` parts for
		most real HTML and 2FA/OTP emails (e.g. ``multipart/mixed`` -> ``multipart/alternative``
		-> ``text/plain``). The previous implementation only scanned the top-level ``parts``
		and matched ``text/plain``/``text/html`` directly, so any body wrapped in an
		intermediate ``multipart/*`` part was silently returned as ``''``.

		Traversal is depth- and count-bounded and decodes each leaf defensively, so a
		malformed or adversarially nested MIME tree degrades to a best-effort body (or
		``''``) instead of raising.
		"""
		# Simple, single-part body
		simple = self._decode_part_data(payload.get('body', {}).get('data'))
		if simple is not None:
			return simple

		plain_chunks: list[str] = []
		html_fallback = ''
		max_depth = 50  # real emails nest a few levels; guards against hostile/recursive trees
		budget = [5000]  # cap total parts visited

		def walk(part: dict[str, Any], depth: int) -> None:
			nonlocal html_fallback
			if depth > max_depth or budget[0] <= 0:
				return
			budget[0] -= 1
			mime_type = part.get('mimeType', '')
			if mime_type == 'text/plain':
				text = self._decode_part_data(part.get('body', {}).get('data'))
				if text is not None:
					plain_chunks.append(text)
			elif mime_type == 'text/html' and not html_fallback:
				text = self._decode_part_data(part.get('body', {}).get('data'))
				if text is not None:
					html_fallback = text
			elif part.get('parts'):
				# ``multipart/*`` container (or any part carrying nested parts) -> recurse
				for sub_part in part['parts']:
					walk(sub_part, depth + 1)

		for part in payload.get('parts', []):
			walk(part, 1)

		# Prefer concatenated plain text; fall back to HTML only when no plain text exists
		if plain_chunks:
			return ''.join(plain_chunks)
		return html_fallback
