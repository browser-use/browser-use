"""
Disposable email for browser-use agents via Agent Burner.
No API key, no signup, no dependencies beyond httpx.

API docs: https://agentburner.com/skill.md
"""

import asyncio
import logging
import re

import httpx

from browser_use import Tools

logger = logging.getLogger(__name__)

API = "https://api.agentburner.com"


class EmailTools(Tools):
	def __init__(self, poll_interval: float = 3.0, poll_timeout: float = 60.0):
		super().__init__()
		self.poll_interval = poll_interval
		self.poll_timeout = poll_timeout
		self.inbox_address: str | None = None
		self.inbox_key: str | None = None
		self.register_email_tools()

	def register_email_tools(self):
		@self.action("Create a disposable email address. Use this when you need to sign up for a service.")
		async def create_email() -> str:
			async with httpx.AsyncClient() as client:
				resp = await client.post(f"{API}/inbox")
				data = resp.json()
			self.inbox_address = data["address"]
			self.inbox_key = data["key"]
			logger.info(f"Created burner inbox: {self.inbox_address}")
			return self.inbox_address

		@self.action("Get the current disposable email address.")
		async def get_email_address() -> str:
			if not self.inbox_address:
				return await create_email()
			return self.inbox_address

		@self.action("Wait for a verification email and return its contents. Use after signing up to get OTP codes or verification links.")
		async def get_verification_email() -> str:
			if not self.inbox_key:
				return "No inbox created yet. Call create_email first."

			elapsed = 0.0
			async with httpx.AsyncClient() as client:
				while elapsed < self.poll_timeout:
					resp = await client.get(f"{API}/inbox/{self.inbox_key}")
					if resp.status_code == 404:
						return "Inbox expired or not found."
					data = resp.json()
					if data.get("entries"):
						entry = data["entries"][0]
						email_resp = await client.get(f"{API}/inbox/{self.inbox_key}/{entry['id']}")
						email = email_resp.json()

						parts = []
						parts.append(f"From: {email.get('from', '')}")
						parts.append(f"Subject: {email.get('subject', '')}")
						parts.append(f"Body: {email.get('body', '')}")
						if email.get("urls"):
							parts.append(f"URLs: {', '.join(email['urls'])}")

						# Extract OTP codes (4-8 digit numbers)
						codes = re.findall(r"\b\d{4,8}\b", email.get("body", ""))
						if codes:
							parts.append(f"Verification codes found: {', '.join(codes)}")

						logger.info(f"Received email from {email.get('from', '')} with subject: {email.get('subject', '')}")
						return "\n".join(parts)

					await asyncio.sleep(self.poll_interval)
					elapsed += self.poll_interval

			return f"No email received after {self.poll_timeout}s."

		@self.action("Get the verification link from the latest email. Returns the first URL found.")
		async def get_verification_link() -> str:
			if not self.inbox_key:
				return "No inbox created yet. Call create_email first."

			async with httpx.AsyncClient() as client:
				resp = await client.get(f"{API}/inbox/{self.inbox_key}")
				if resp.status_code == 404:
					return "Inbox expired or not found."
				data = resp.json()
				if not data.get("entries"):
					return "No emails received yet."

				entry = data["entries"][0]
				email_resp = await client.get(f"{API}/inbox/{self.inbox_key}/{entry['id']}")
				email = email_resp.json()

				urls = email.get("urls", [])
				if urls:
					return urls[0]
				return "No URLs found in email."

		@self.action("Delete the disposable inbox. Call this when done with the email.")
		async def delete_inbox() -> str:
			if not self.inbox_key:
				return "No inbox to delete."
			async with httpx.AsyncClient() as client:
				await client.delete(f"{API}/inbox/{self.inbox_key}")
			logger.info(f"Deleted inbox: {self.inbox_address}")
			self.inbox_address = None
			self.inbox_key = None
			return "Inbox deleted."
