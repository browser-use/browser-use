"""Screenshot watchdog for handling screenshot requests using CDP."""

from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.page import CaptureScreenshotParameters

from browser_use.browser.events import ScreenshotEvent
from browser_use.browser.views import BrowserError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	pass


class ScreenshotWatchdog(BaseWatchdog):
	"""Handles screenshot requests using CDP."""

	# Events this watchdog listens to
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [ScreenshotEvent]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	@observe_debug(ignore_input=True, ignore_output=True, name='screenshot_event_handler')
	async def on_ScreenshotEvent(self, event: ScreenshotEvent) -> str:
		"""Handle screenshot request using CDP.

		Args:
			event: ScreenshotEvent with optional full_page and clip parameters

		Returns:
			Dict with 'screenshot' key containing base64-encoded screenshot or None
		"""
		self.logger.debug('[ScreenshotWatchdog] Handler START - on_ScreenshotEvent called')
		try:
			# Validate focused target is a top-level page (not iframe/worker)
			# CDP Page.captureScreenshot only works on page/tab targets
			focused_target = self.browser_session.get_focused_target()

			if focused_target and focused_target.target_type in ('page', 'tab'):
				target_id = focused_target.target_id
			else:
				# Focused target is iframe/worker/missing - fall back to any page target
				target_type_str = focused_target.target_type if focused_target else 'None'
				self.logger.warning(f'[ScreenshotWatchdog] Focused target is {target_type_str}, falling back to page target')
				page_targets = self.browser_session.get_page_targets()
				if not page_targets:
					raise BrowserError('[ScreenshotWatchdog] No page targets available for screenshot')
				target_id = page_targets[-1].target_id

			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=True)

			# Prepare screenshot parameters
			params = CaptureScreenshotParameters(format='png', captureBeyondViewport=False)

			# Take screenshot using CDP
			self.logger.debug(f'[ScreenshotWatchdog] Taking screenshot with params: {params}')
			result = await cdp_session.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp_session.session_id)

			# Return base64-encoded screenshot data
			if result and 'data' in result:
				self.logger.debug('[ScreenshotWatchdog] Screenshot captured successfully')
				return result['data']

			raise BrowserError('[ScreenshotWatchdog] Screenshot result missing data')
		except Exception as e:
			self.logger.error(f'[ScreenshotWatchdog] Screenshot failed: {e}')
			raise
		finally:
			# Try to remove highlights even on failure
			try:
				await self.browser_session.remove_highlights()
			except Exception:
				pass
