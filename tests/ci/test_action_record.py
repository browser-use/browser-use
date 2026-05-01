"""Tests for the RecordingWatchdog start/stop API and the `browser-use record` CLI command.

The watchdog drives CDP screencast (`Page.startScreencast`/`stopScreencast`) and
`VideoRecorderService` (imageio+ffmpeg) to produce an MP4. These tests exercise
the full stack against a real headless browser.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

try:
	import imageio.v2 as iio  # type: ignore[import-not-found]

	IMAGEIO_AVAILABLE = True
except ImportError:
	IMAGEIO_AVAILABLE = False

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

pytestmark = pytest.mark.skipif(
	not IMAGEIO_AVAILABLE,
	reason='Recording requires the [video] extra: pip install "browser-use[video]"',
)


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


@pytest.fixture
def page_url(httpserver):
	httpserver.expect_request('/recpage').respond_with_data(
		"""
		<html>
			<body style='background:#f0f;padding:40px;'>
				<h1 id='title'>Recording test</h1>
				<p>This content should appear in the captured video.</p>
			</body>
		</html>
		""",
		content_type='text/html',
	)
	return httpserver.url_for('/recpage')


async def _drive_browser_briefly(bs: BrowserSession, url: str, ticks: int = 8) -> None:
	"""Navigate + poke the page so screencast emits a few frames."""
	await bs.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
	# Screencast emits frames as the page changes; give it enough time to collect some
	for _ in range(ticks):
		await asyncio.sleep(0.15)


async def test_start_stop_recording_produces_video(browser_session: BrowserSession, page_url: str, tmp_path: Path):
	"""start_recording → activity → stop_recording should write a valid MP4."""
	watchdog = browser_session._recording_watchdog
	assert watchdog is not None, 'BrowserSession should always attach a RecordingWatchdog'

	out_path = tmp_path / 'session.mp4'
	assert not watchdog.is_recording

	saved = await watchdog.start_recording(out_path)
	assert saved == out_path
	assert watchdog.is_recording

	await _drive_browser_briefly(browser_session, page_url)

	final = await watchdog.stop_recording()
	assert final == out_path
	assert not watchdog.is_recording
	assert out_path.exists(), 'recording stop should leave a file on disk'
	assert out_path.stat().st_size > 0, 'recorded video must be non-empty'

	# Confirm the file is actually a decodable video with at least one frame.
	reader: Any = iio.get_reader(str(out_path))
	try:
		frame: Any = reader.get_next_data()
		assert frame is not None and frame.size > 0
	finally:
		reader.close()


async def test_start_recording_twice_raises(browser_session: BrowserSession, tmp_path: Path):
	watchdog = browser_session._recording_watchdog
	assert watchdog is not None

	await watchdog.start_recording(tmp_path / 'first.mp4')
	try:
		with pytest.raises(RuntimeError, match='already in progress'):
			await watchdog.start_recording(tmp_path / 'second.mp4')
	finally:
		await watchdog.stop_recording()


async def test_stop_without_start_returns_none(browser_session: BrowserSession):
	watchdog = browser_session._recording_watchdog
	assert watchdog is not None
	assert await watchdog.stop_recording() is None


async def test_on_browser_connected_degrades_gracefully_when_recording_fails(
	browser_session: BrowserSession, tmp_path: Path, monkeypatch
):
	"""If start_recording() raises (e.g. missing [video] deps), profile-driven recording
	must degrade to a warning instead of breaking BrowserSession startup (see PR #4710 review)."""
	from browser_use.browser.events import BrowserConnectedEvent
	from browser_use.browser.watchdogs import recording_watchdog as rw_mod

	watchdog = browser_session._recording_watchdog
	assert watchdog is not None

	async def fake_start_recording(self: Any, *_args: Any, **_kwargs: Any) -> Path:
		raise RuntimeError('simulated missing video deps')

	monkeypatch.setattr(rw_mod.RecordingWatchdog, 'start_recording', fake_start_recording)
	browser_session.browser_profile.record_video_dir = tmp_path

	# Must not raise — watchdog should catch the RuntimeError and just log a warning.
	await watchdog.on_BrowserConnectedEvent(BrowserConnectedEvent(cdp_url=browser_session.cdp_url or ''))
	assert not watchdog.is_recording


async def test_profile_record_video_dir_still_works(page_url: str, tmp_path: Path):
	"""The existing event-driven flow (profile.record_video_dir) must keep working."""
	session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, record_video_dir=tmp_path),
	)
	await session.start()
	try:
		watchdog = session._recording_watchdog
		assert watchdog is not None
		# on_BrowserConnectedEvent should have auto-started recording via the watchdog
		assert watchdog.is_recording, 'profile.record_video_dir should have auto-started recording'
		await _drive_browser_briefly(session, page_url)
	finally:
		await session.kill()

	# After kill, BrowserStopEvent should have finalized the video file into tmp_path
	videos = list(tmp_path.glob('*.mp4'))
	assert videos, f'expected at least one recorded mp4 in {tmp_path}'
	assert videos[0].stat().st_size > 0


# ---------------------------------------------------------------------------
# CLI plumbing (argparse + command routing)
# ---------------------------------------------------------------------------


def test_cli_argparse_record_start_stop():
	"""`browser-use record start <path>` and `record stop` parse correctly."""
	from browser_use.skill_cli.main import build_parser

	parser = build_parser()

	args = parser.parse_args(['record', 'start', '/tmp/x.mp4'])
	assert args.command == 'record'
	assert args.record_command == 'start'
	assert args.path == '/tmp/x.mp4'

	args = parser.parse_args(['record', 'stop'])
	assert args.command == 'record'
	assert args.record_command == 'stop'

	args = parser.parse_args(['record', 'status'])
	assert args.command == 'record'
	assert args.record_command == 'status'


def test_cli_record_is_routed_to_browser_handler():
	"""Daemon dispatch should route 'record' to browser.handle()."""
	from browser_use.skill_cli.commands import browser as browser_cmd

	assert 'record' in browser_cmd.COMMANDS
