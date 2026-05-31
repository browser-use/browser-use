from typing import Any


async def attach_all_watchdogs(browser_session: Any) -> None:
	"""Initialize and attach browser watchdogs for a session."""
	if browser_session._watchdogs_attached:
		browser_session.logger.debug('Watchdogs already attached, skipping duplicate attachment')
		return

	from browser_use.browser.watchdogs.aboutblank_watchdog import AboutBlankWatchdog
	from browser_use.browser.watchdogs.captcha_watchdog import CaptchaWatchdog
	from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
	from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
	from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog
	from browser_use.browser.watchdogs.har_recording_watchdog import HarRecordingWatchdog
	from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
	from browser_use.browser.watchdogs.permissions_watchdog import PermissionsWatchdog
	from browser_use.browser.watchdogs.recording_watchdog import RecordingWatchdog
	from browser_use.browser.watchdogs.screenshot_watchdog import ScreenshotWatchdog
	from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog
	from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog

	DownloadsWatchdog.model_rebuild()
	browser_session._downloads_watchdog = DownloadsWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._downloads_watchdog.attach_to_session()
	if browser_session.browser_profile.auto_download_pdfs:
		browser_session.logger.debug('📄 PDF auto-download enabled for this session')

	should_enable_storage_state = (
		browser_session.browser_profile.storage_state is not None or browser_session.browser_profile.user_data_dir is not None
	)

	if should_enable_storage_state:
		StorageStateWatchdog.model_rebuild()
		browser_session._storage_state_watchdog = StorageStateWatchdog(
			event_bus=browser_session.event_bus,
			browser_session=browser_session,
			auto_save_interval=60.0,
			save_on_change=False,
		)
		browser_session._storage_state_watchdog.attach_to_session()
		browser_session.logger.debug(
			f'🍪 StorageStateWatchdog enabled (storage_state: {bool(browser_session.browser_profile.storage_state)}, user_data_dir: {bool(browser_session.browser_profile.user_data_dir)})'
		)
	else:
		browser_session.logger.debug('🍪 StorageStateWatchdog disabled (no storage_state or user_data_dir configured)')

	LocalBrowserWatchdog.model_rebuild()
	browser_session._local_browser_watchdog = LocalBrowserWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._local_browser_watchdog.attach_to_session()

	SecurityWatchdog.model_rebuild()
	browser_session._security_watchdog = SecurityWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._security_watchdog.attach_to_session()

	AboutBlankWatchdog.model_rebuild()
	browser_session._aboutblank_watchdog = AboutBlankWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._aboutblank_watchdog.attach_to_session()

	PermissionsWatchdog.model_rebuild()
	browser_session._permissions_watchdog = PermissionsWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._permissions_watchdog.attach_to_session()

	DefaultActionWatchdog.model_rebuild()
	browser_session._default_action_watchdog = DefaultActionWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._default_action_watchdog.attach_to_session()

	ScreenshotWatchdog.model_rebuild()
	browser_session._screenshot_watchdog = ScreenshotWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._screenshot_watchdog.attach_to_session()

	DOMWatchdog.model_rebuild()
	browser_session._dom_watchdog = DOMWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._dom_watchdog.attach_to_session()

	RecordingWatchdog.model_rebuild()
	browser_session._recording_watchdog = RecordingWatchdog(
		event_bus=browser_session.event_bus,
		browser_session=browser_session,
	)
	browser_session._recording_watchdog.attach_to_session()

	if browser_session.browser_profile.record_har_path:
		HarRecordingWatchdog.model_rebuild()
		browser_session._har_recording_watchdog = HarRecordingWatchdog(
			event_bus=browser_session.event_bus,
			browser_session=browser_session,
		)
		browser_session._har_recording_watchdog.attach_to_session()

	if browser_session.browser_profile.captcha_solver:
		CaptchaWatchdog.model_rebuild()
		browser_session._captcha_watchdog = CaptchaWatchdog(
			event_bus=browser_session.event_bus,
			browser_session=browser_session,
		)
		browser_session._captcha_watchdog.attach_to_session()

	browser_session._watchdogs_attached = True
