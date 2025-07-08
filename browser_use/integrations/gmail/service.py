"""
Gmail API Service for Browser Use
Handles Gmail API authentication, email reading, and 2FA code extraction.
This service provides a clean interface for agents to interact with Gmail.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import aiofiles
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
				async with aiofiles.open(self.token_file, 'w') as token:
					await token.write(self.creds.to_json())
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

	def _extract_body(self, payload: dict[str, Any]) -> str:
		"""Extract email body from payload"""
		body = ''

		if payload.get('body', {}).get('data'):
			# Simple email body
			body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
		elif payload.get('parts'):
			# Multi-part email
			for part in payload['parts']:
				if part['mimeType'] == 'text/plain' and part.get('body', {}).get('data'):
					part_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
					body += part_body
				elif part['mimeType'] == 'text/html' and not body and part.get('body', {}).get('data'):
					# Fallback to HTML if no plain text
					body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')

		return body
