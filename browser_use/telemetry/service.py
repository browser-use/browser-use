import logging
import os

from dotenv import load_dotenv
from uuid_extensions import uuid7str

from browser_use.telemetry.views import BaseTelemetryEvent
from browser_use.utils import singleton

load_dotenv()

from browser_use.config import CONFIG

logger = logging.getLogger(__name__)


POSTHOG_EVENT_SETTINGS = {
	'process_person_profile': True,
}

POSTHOG_PROJECT_API_KEY = 'phc_F8JMNjW1i2KbGUTaW1unnDdLSPCoyc52SGRU0JecaUh'
POSTHOG_HOST = 'https://eu.i.posthog.com'
DEVICE_ID_PATH = str(CONFIG.BROWSER_USE_CONFIG_DIR / 'device_id')

_device_id: str | None = None


def get_or_create_device_id() -> str:
	"""Return the anonymous device id shared by telemetry"""
	global _device_id
	if _device_id:
		return _device_id
	_device_id = os.environ.get('BROWSER_USE_DEVICE_ID') or _persisted_device_id() or _machine_fingerprint() or uuid7str()
	return _device_id


def _persisted_device_id() -> str | None:
	try:
		if os.path.exists(DEVICE_ID_PATH):
			with open(DEVICE_ID_PATH) as f:
				return f.read().strip() or None
		os.makedirs(os.path.dirname(DEVICE_ID_PATH), exist_ok=True)
		new_device_id = uuid7str()
		tmp_path = f'{DEVICE_ID_PATH}.{os.getpid()}.tmp'
		with open(tmp_path, 'w') as f:
			f.write(new_device_id)
		os.replace(tmp_path, DEVICE_ID_PATH)
		return new_device_id
	except Exception:
		return None


def _machine_fingerprint() -> str | None:
	"""Hashed hardware-derived id"""
	import hashlib
	import socket
	import uuid

	node = uuid.getnode()
	if (node >> 40) & 0x01:  # multicast bit set: getnode() failed and returned a random id
		return None
	return 'bu_' + hashlib.sha256(f'browser-use:{node}:{socket.gethostname()}'.encode()).hexdigest()[:32]


@singleton
class ProductTelemetry:
	"""
	Service for capturing anonymized telemetry data.

	If the environment variable `ANONYMIZED_TELEMETRY=False`, anonymized telemetry will be disabled.
	"""

	PROJECT_API_KEY = POSTHOG_PROJECT_API_KEY
	HOST = POSTHOG_HOST

	_curr_user_id = None

	def __init__(self) -> None:
		telemetry_disabled = not CONFIG.ANONYMIZED_TELEMETRY
		self.debug_logging = CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug'

		if telemetry_disabled:
			self._posthog_client = None
		else:
			from posthog import Posthog

			logger.info('Using anonymized telemetry, see https://docs.browser-use.com/development/monitoring/telemetry.')
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

		self._direct_capture(event)

	def _direct_capture(self, event: BaseTelemetryEvent) -> None:
		"""
		Should not be thread blocking because posthog magically handles it
		"""
		if self._posthog_client is None:
			return

		try:
			self._posthog_client.capture(
				distinct_id=self.user_id,
				event=event.name,
				properties={**event.properties, **POSTHOG_EVENT_SETTINGS},
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

		self._curr_user_id = get_or_create_device_id()
		return self._curr_user_id
