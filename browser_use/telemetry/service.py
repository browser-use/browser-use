import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from posthog import Posthog
from uuid_extensions import uuid7str

from browser_use.telemetry.views import BaseTelemetryEvent
from browser_use.utils import singleton

load_dotenv()


logger = logging.getLogger(__name__)


POSTHOG_EVENT_SETTINGS = {
	'process_person_profile': True,
}


def xdg_cache_home() -> Path:
	default = Path.home() / '.cache'
	env_var = os.getenv('XDG_CACHE_HOME')
	if env_var and (path := Path(env_var)).is_absolute():
		return path
	return default


@singleton
class ProductTelemetry:
	"""
	Service for capturing anonymized telemetry data.

	If the environment variable `ANONYMIZED_TELEMETRY=False`, anonymized telemetry will be disabled.
	"""

	USER_ID_PATH = str(xdg_cache_home() / 'browser_use' / 'telemetry_user_id')
	PROJECT_API_KEY = 'phc_F8JMNjW1i2KbGUTaW1unnDdLSPCoyc52SGRU0JecaUh'
	HOST = 'https://eu.i.posthog.com'
	UNKNOWN_USER_ID = 'UNKNOWN'

	_curr_user_id = None

	def __init__(self) -> None:
		telemetry_disabled = os.getenv('ANONYMIZED_TELEMETRY', 'true').lower() == 'false'
		self.debug_logging = os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info').lower() == 'debug'

		if telemetry_disabled:
			self._posthog_client = None
		else:
			logger.info(
				'Anonymized telemetry enabled. See https://docs.browser-use.com/development/telemetry for more information.'
			)
			self._posthog_client = Posthog(
				project_api_key=self.PROJECT_API_KEY,
				host=self.HOST,
				disable_geoip=False,
				enable_exception_autocapture=True,
			)

			# Silence posthog's logging
			if not self.debug_logging:
				posthog_logger = logging.getLogger('posthog')
				posthog_logger.disabled = True

		if self._posthog_client is None:
			logger.debug('Telemetry disabled')

	def capture(self, event: BaseTelemetryEvent) -> None:
		if self._posthog_client is None:
			return

		if self.debug_logging:
			logger.debug(f'Telemetry event: {event.name} {event.properties}')
		self._direct_capture(event)

	def _direct_capture(self, event: BaseTelemetryEvent) -> None:
		"""
		Should not be thread blocking because posthog magically handles it
		"""
		if self._posthog_client is None:
			return

		try:
			self._posthog_client.capture(
				self.user_id,
				event.name,
				{**event.properties, **POSTHOG_EVENT_SETTINGS},
			)
		except Exception as e:
			logger.error(f'Failed to send telemetry event {event.name}: {e}')

	def flush(self) -> None:
		if self._posthog_client:
			try:
				self._posthog_client.flush()
				logger.debug('PostHog client telemetry queue flushed.')
			except Exception as e:
				logger.error(f'Failed to flush PostHog client: {e}')
		else:
			logger.debug('PostHog client not available, skipping flush.')

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
					new_user_id = uuid7str()
					f.write(new_user_id)
				self._curr_user_id = new_user_id
			else:
				with open(self.USER_ID_PATH) as f:
					self._curr_user_id = f.read()
		except Exception:
			self._curr_user_id = 'UNKNOWN_USER_ID'
		return self._curr_user_id
