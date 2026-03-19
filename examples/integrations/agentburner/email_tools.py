"""
Disposable email for browser-use agents via Agent Burner.
No API key, no signup, no SDK — just HTTP.

API docs: https://agentburner.com/skill.md
"""

import logging

import httpx

from browser_use import Tools

logger = logging.getLogger(__name__)

API = 'https://api.agentburner.com'


class EmailTools(Tools):
	def __init__(self) -> None:
		super().__init__()
		self.inbox_address: str | None = None
		self.inbox_key: str | None = None
		self._register()

	def _register(self) -> None:
		@self.action('Create a disposable email inbox. Returns the email address.')
		async def create_inbox() -> str:
			async with httpx.AsyncClient() as client:
				resp = await client.post(f'{API}/inbox')
				resp.raise_for_status()
				data = resp.json()
			self.inbox_address = data['address']
			self.inbox_key = data['key']
			logger.info(f'Created inbox: {self.inbox_address}')
			return str(self.inbox_address)

		@self.action('List emails in the inbox. Returns a JSON string with entries (id, from, subject, receivedAt).')
		async def list_emails() -> str:
			if not self.inbox_key:
				return 'No inbox created. Call create_inbox first.'
			async with httpx.AsyncClient() as client:
				resp = await client.get(f'{API}/inbox/{self.inbox_key}')
				if resp.status_code == 404:
					return 'Inbox expired or not found.'
				resp.raise_for_status()
			return resp.text

		@self.action('Get a full email by ID. Returns JSON with body, html, urls[], from, subject.')
		async def get_email(email_id: str) -> str:
			if not self.inbox_key:
				return 'No inbox created. Call create_inbox first.'
			async with httpx.AsyncClient() as client:
				resp = await client.get(f'{API}/inbox/{self.inbox_key}/{email_id}')
				if resp.status_code == 404:
					return 'Email not found.'
				resp.raise_for_status()
			return resp.text

		@self.action('Delete the inbox. Optional — inboxes auto-expire in 1 hour.')
		async def delete_inbox() -> str:
			if not self.inbox_key:
				return 'No inbox to delete.'
			async with httpx.AsyncClient() as client:
				resp = await client.delete(f'{API}/inbox/{self.inbox_key}')
				if resp.status_code not in (200, 404):
					return f'Failed to delete: HTTP {resp.status_code}'
			logger.info(f'Deleted inbox: {self.inbox_address}')
			self.inbox_address = None
			self.inbox_key = None
			return 'Inbox deleted.'
