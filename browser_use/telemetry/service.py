import logging
import os
import uuid
import asyncio
import boto3
from pathlib import Path
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict
import json

from dotenv import load_dotenv
from posthog import Posthog

from browser_use.telemetry.views import (
	BaseTelemetryEvent,
	AgentStepTelemetryEvent,
	AgentRunTelemetryEvent,
	AgentEndTelemetryEvent,
	LLMCallTelemetryEvent,
)
from browser_use.utils import singleton

load_dotenv()

logger = logging.getLogger(__name__)

POSTHOG_EVENT_SETTINGS = {
	'process_person_profile': True,
}

@singleton
class ProductTelemetry:
	"""
	Service for capturing anonymized telemetry data and logging structured events.
	"""

	def __init__(self) -> None:
		self.session_id = None
		self.command_id = None

	def set_context(self, session_id=None, command_id=None):
		if session_id is not None:
			self.session_id = session_id
		if command_id is not None:
			self.command_id = command_id

	def capture(self, event: BaseTelemetryEvent) -> None:
		# Always include session_id and command_id if available
		event_dict = {
			"event_type": getattr(event, 'name', type(event).__name__),
			**getattr(event, 'properties', {})
		}
		# Try to get from event, else from self
		session_id = getattr(event, 'session_id', None) or self.session_id
		command_id = getattr(event, 'command_id', None) or self.command_id
		if session_id is not None:
			event_dict['session_id'] = session_id
		if command_id is not None:
			event_dict['command_id'] = command_id
		logger.info(json.dumps(event_dict))

	@property
	def user_id(self) -> str:
		if self._curr_user_id:
			return self._curr_user_id

		# File access may fail due to permissions or other reasons. We don't want to
		# crash so we catch all exceptions.
		try:
			if not os.path.exists(self.USER_ID_PATH):
				os.makedirs(os.path.dirname(self.USER_ID_PATH), exist_ok=True)
				with open(self.USER_ID_PATH, 'w') as f:
					new_user_id = str(uuid.uuid4())
					f.write(new_user_id)
				self._curr_user_id = new_user_id
			else:
				with open(self.USER_ID_PATH, 'r') as f:
					self._curr_user_id = f.read()
		except Exception:
			self._curr_user_id = 'UNKNOWN_USER_ID'
		return self._curr_user_id
