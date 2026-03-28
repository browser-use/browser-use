"""
Phone verification tools for Browser Use using AgentSIM.

AgentSIM provides real carrier-grade (T-Mobile) phone numbers that pass
carrier lookup checks as line_type: mobile. Unlike VoIP numbers (Twilio,
Google Voice), these numbers work with services that block virtual numbers.

Install: pip install agentsim-sdk
API key: https://agentsim.dev/dashboard
"""

import asyncio
import logging

import agentsim
from agentsim.types import OtpResult, PhoneSession

from browser_use import ActionResult, Tools

logger = logging.getLogger(__name__)


class PhoneTools(Tools):
	"""Browser Use tools for phone number provisioning and OTP verification via AgentSIM."""

	def __init__(self, api_key: str | None = None, default_country: str = "US"):
		super().__init__()
		if api_key:
			agentsim.configure(api_key=api_key)
		self.default_country = default_country
		self._sessions: dict[str, PhoneSession] = {}
		self._register_tools()

	def _register_tools(self) -> None:
		@self.action(
			description=(
				"Provision a real carrier-grade mobile phone number via AgentSIM. "
				"Call this BEFORE entering a phone number on any SMS verification page. "
				"Returns the phone number in E.164 format (e.g. +14155551234) and a "
				"session_id needed for OTP retrieval. The number is a real T-Mobile SIM "
				"that passes carrier lookup checks — not VoIP."
			)
		)
		async def provision_phone_number(country: str = self.default_country) -> ActionResult:
			session = await agentsim.provision_number(agent_id="browser-use", country=country)
			self._sessions[session.session_id] = session
			logger.info(f"Provisioned {session.number} (session: {session.session_id})")
			return ActionResult(
				extracted_content=(
					f"Provisioned phone number: {session.number} "
					f"(session_id: {session.session_id}). "
					f"Enter this number in the phone field and submit the form. "
					f"Then call wait_for_otp with session_id={session.session_id}."
				),
				include_in_memory=True,
			)

		@self.action(
			description=(
				"Wait for an SMS OTP to arrive on a provisioned AgentSIM number. "
				"Call this AFTER the phone number form has been submitted. "
				"Returns the OTP code to enter in the verification field. "
				"Waits up to timeout_seconds (default 60)."
			)
		)
		async def wait_for_otp(session_id: str, timeout_seconds: int = 60) -> ActionResult:
			session = self._sessions.get(session_id)
			if not session:
				return ActionResult(
					extracted_content=f"No active session found for {session_id}. Provision a number first.",
					include_in_memory=True,
				)
			try:
				otp: OtpResult = await session.wait_for_otp(timeout=timeout_seconds)
				logger.info(f"OTP received for session {session_id}: {otp.otp_code}")
				return ActionResult(
					extracted_content=(
						f"OTP received: {otp.otp_code}. "
						f"Enter this code in the verification/OTP field and submit."
					),
					include_in_memory=True,
				)
			except agentsim.OtpTimeoutError:
				return ActionResult(
					extracted_content=(
						"OTP timed out — the SMS may not have been sent yet. "
						"Make sure you submitted the form with the phone number, then try again."
					),
					include_in_memory=True,
				)

		@self.action(
			description=(
				"Release an AgentSIM phone number back to the pool. "
				"Call this after SMS verification is complete to avoid extra charges."
			)
		)
		async def release_phone_number(session_id: str) -> ActionResult:
			session = self._sessions.pop(session_id, None)
			if session:
				await session.release()
				logger.info(f"Released session {session_id}")
			return ActionResult(
				extracted_content=f"Phone number released (session {session_id}).",
				include_in_memory=True,
			)
