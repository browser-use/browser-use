"""
Email management to enable 2fa.
"""

import asyncio
import logging

# run `pip install agentmail` to install the library
from agentmail import AsyncAgentMail, Message, MessageReceivedEvent, Subscribe  # type: ignore
from agentmail.inboxes.types.inbox import Inbox  # type: ignore
from agentmail.inboxes.types.inbox_id import InboxId  # type: ignore

from browser_use import Tools

# Configure basic logging if not already configured
if not logging.getLogger().handlers:
	logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

logger = logging.getLogger(__name__)


class EmailTools(Tools):
	def __init__(
		self,
		email_client: AsyncAgentMail | None = None,
		email_timeout: int = 30,
		inbox: Inbox | None = None,
	):
		super().__init__()
		self.email_client = email_client or AsyncAgentMail()

		self.email_timeout = email_timeout

		self.register_email_tools()

		self.inbox: Inbox | None = inbox

	def _serialize_message_for_llm(self, message: Message) -> str:
		"""
		Serialize a message for the LLM
		"""
		# Use text if available, otherwise convert HTML to simple text
		body_content = message.text
		if not body_content and message.html:
			body_content = self._html_to_text(message.html)

		msg = f'From: {message.from_}\nTo: {message.to}\nTimestamp: {message.timestamp.isoformat()}\nSubject: {message.subject}\nBody: {body_content}'
		return msg

	def _html_to_text(self, html: str) -> str:
		"""
		Simple HTML to text conversion
		"""
		import re

		# Remove script and style elements - handle spaces in closing tags
		html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
		html = re.sub(r'<style\b[^>]*>.*?</style\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)

		# Remove HTML tags
		html = re.sub(r'<[^>]+>', '', html)

		# Decode HTML entities
		html = html.replace('&nbsp;', ' ')
		html = html.replace('&amp;', '&')
		html = html.replace('&lt;', '<')
		html = html.replace('&gt;', '>')
		html = html.replace('&quot;', '"')
		html = html.replace('&#39;', "'")

		# Clean up whitespace
		html = re.sub(r'\s+', ' ', html)
		html = html.strip()

		return html

	async def get_or_create_inbox_client(self) -> Inbox:
		"""
		Create a default inbox profile for this API key (assume that agent is on free tier)

		If you are not on free tier it is recommended to create 1 inbox per agent.
		"""
		if self.inbox:
			return self.inbox

		return await self.create_inbox_client()

	async def create_inbox_client(self) -> Inbox:
		"""
		Create a default inbox profile for this API key (assume that agent is on free tier)

		If you are not on free tier it is recommended to create 1 inbox per agent.
		"""
		inbox = await self.email_client.inboxes.create()
		self.inbox = inbox
		return inbox

	async def wait_for_message(self, inbox_id: InboxId) -> Message:
		"""
		Wait for a message to be received in the inbox
		"""
		async with self.email_client.websockets.connect() as ws:
			await ws.send_subscribe(message=Subscribe(inbox_ids=[inbox_id]))

			try:
				while True:
					data = await asyncio.wait_for(ws.recv(), timeout=self.email_timeout)
					if isinstance(data, MessageReceivedEvent):
						await self.email_client.inboxes.messages.update(
							inbox_id=inbox_id, message_id=data.message.message_id, remove_labels=['unread']
						)
						msg = data.message
						logger.info(f'Received new message from: {msg.from_} with subject: {msg.subject}')
						return msg
					# If not MessageReceived, continue waiting for the next event
			except TimeoutError:
				raise TimeoutError(f'No email received in the inbox in {self.email_timeout}s')

	def register_email_tools(self):
		"""Register all email-related controller actions"""

		@self.action('Get email address for login. You can use this email to login to any service with email and password')
		async def get_email_address() -> str:
			"""
			Get the email address of the inbox
			"""
			inbox = await self.get_or_create_inbox_client()
			logger.info(f'Email address: {inbox.inbox_id}')
			return inbox.inbox_id

		@self.action(
			'Get the latest unread email from the inbox from the last max_age_minutes (default 5 minutes). Waits some seconds for new emails if none found. Use for 2FA codes.'
		)
		async def get_latest_email(max_age_minutes: int = 5) -> str:
			"""
			1. Check for unread emails within the last max_age_minutes
			2. If no recent unread email, wait 30 seconds for new email via websocket
			"""
			from datetime import datetime, timedelta, timezone

			inbox = await self.get_or_create_inbox_client()

			# Get unread emails
			emails = await self.email_client.inboxes.messages.list(inbox_id=inbox.inbox_id, labels=['unread'])
			# Filter unread emails by time window - use UTC timezone to match email timestamps
			time_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
			logger.debug(f'Time cutoff: {time_cutoff}')
			logger.info(f'Found {len(emails.messages)} unread emails for inbox {inbox.inbox_id}')
			recent_unread_emails = []

			for i, email_summary in enumerate(emails.messages):
				# Get full email details to check timestamp
				full_email = await self.email_client.inboxes.messages.get(
					inbox_id=inbox.inbox_id, message_id=email_summary.message_id
				)
				# Handle timezone comparison properly
				email_timestamp = full_email.timestamp
				if email_timestamp.tzinfo is None:
					# If email timestamp is naive, assume UTC
					email_timestamp = email_timestamp.replace(tzinfo=timezone.utc)

				if email_timestamp >= time_cutoff:
					recent_unread_emails.append(full_email)

			# If we have recent unread emails, return the latest one
			if recent_unread_emails:
				# Sort by timestamp and get the most recent
				recent_unread_emails.sort(key=lambda x: x.timestamp, reverse=True)
				logger.info(f'Found {len(recent_unread_emails)} recent unread emails for inbox {inbox.inbox_id}')

				latest_email = recent_unread_emails[0]

				# Mark as read
				await self.email_client.inboxes.messages.update(
					inbox_id=inbox.inbox_id, message_id=latest_email.message_id, remove_labels=['unread']
				)
				logger.info(f'Latest email from: {latest_email.from_} with subject: {latest_email.subject}')
				return self._serialize_message_for_llm(latest_email)
			else:
				logger.info('No recent unread emails, waiting for a new one')
			# No recent unread emails, wait for new one
			try:
				latest_message = await self.wait_for_message(inbox_id=inbox.inbox_id)
			except TimeoutError:
				return f'No email received in the inbox in {self.email_timeout}s'
			# logger.info(f'Latest message: {latest_message}')
			return self._serialize_message_for_llm(latest_message)
