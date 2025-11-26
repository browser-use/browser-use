"""Recording Watchdog for Browser Use Sessions."""

import asyncio
from pathlib import Path
from typing import ClassVar

from bubus import BaseEvent
from cdp_use.cdp.page.events import ScreencastFrameEvent
from uuid_extensions import uuid7str

from browser_use.browser.events import BrowserConnectedEvent, BrowserStopEvent
from browser_use.browser.profile import ViewportSize
from browser_use.browser.video_recorder import VideoRecorderService
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import create_task_with_error_handling


class RecordingWatchdog(BaseWatchdog):
	"""
	Manages video recording of a browser session using CDP screencasting.
	"""

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [BrowserConnectedEvent, BrowserStopEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	_recorder: VideoRecorderService | None = None

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""
		Starts video recording if it is configured in the browser profile.
		"""
		profile = self.browser_session.browser_profile
		if not profile.record_video_dir:
			return

		# Dynamically determine video size
		size = profile.record_video_size
		if not size:
			self.logger.debug('record_video_size not specified, detecting viewport size...')
			size = await self._get_current_viewport_size()

		if not size:
			self.logger.warning('Cannot start video recording: viewport size could not be determined.')
			return

		video_format = getattr(profile, 'record_video_format', 'mp4').strip('.')
		output_path = Path(profile.record_video_dir) / f'{uuid7str()}.{video_format}'

		self.logger.debug(f'Initializing video recorder for format: {video_format}')
		self._recorder = VideoRecorderService(output_path=output_path, size=size, framerate=profile.record_video_framerate)
		self._recorder.start()

		if not self._recorder._is_active:
			self._recorder = None
			return

		self.browser_session.cdp_client.register.Page.screencastFrame(self.on_screencastFrame)

		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			await cdp_session.cdp_client.send.Page.startScreencast(
				params={
					'format': 'png',
					'quality': 90,
					'maxWidth': size['width'],
					'maxHeight': size['height'],
					'everyNthFrame': 1,
				},
				session_id=cdp_session.session_id,
			)
			self.logger.info(f'📹 Started video recording to {output_path}')
		except Exception as e:
			self.logger.error(f'Failed to start screencast via CDP: {e}')
			if self._recorder:
				self._recorder.stop_and_save()
				self._recorder = None

	async def _get_current_viewport_size(self) -> ViewportSize | None:
		"""Gets the current viewport size directly from the browser via CDP."""
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)

			# Use cssVisualViewport for the most accurate representation of the visible area
			viewport = metrics.get('cssVisualViewport', {})
			width = viewport.get('clientWidth')
			height = viewport.get('clientHeight')

			if width and height:
				self.logger.debug(f'Detected viewport size: {width}x{height}')
				return ViewportSize(width=int(width), height=int(height))
		except Exception as e:
			self.logger.warning(f'Failed to get viewport size from browser: {e}')

		return None

	def on_screencastFrame(self, event: ScreencastFrameEvent, session_id: str | None) -> None:
		"""
		Synchronous handler for incoming screencast frames.
		"""

		if not self._recorder:
			return
		self._recorder.add_frame(event['data'])
		create_task_with_error_handling(
			self._ack_screencast_frame(event, session_id),
			name='ack_screencast_frame',
			logger_instance=self.logger,
			suppress_exceptions=True,
		)

	async def _ack_screencast_frame(self, event: ScreencastFrameEvent, session_id: str | None) -> None:
		"""
		Asynchronously acknowledges a screencast frame.
		"""
		try:
			await self.browser_session.cdp_client.send.Page.screencastFrameAck(
				params={'sessionId': event['sessionId']}, session_id=session_id
			)
		except Exception as e:
			self.logger.debug(f'Failed to acknowledge screencast frame: {e}')

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""
		Stops the video recording and finalizes the video file.
		"""
		if self._recorder:
			recorder = self._recorder
			self._recorder = None

			self.logger.debug('Stopping video recording and saving file...')
			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, recorder.stop_and_save)
