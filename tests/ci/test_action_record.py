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

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile, ViewportSize
from browser_use.browser.session import BrowserSession
from tests.ci.conftest import create_mock_llm

# Mark that gates tests requiring actual video recording/playback
requires_video = pytest.mark.skipif(
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


@requires_video
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


@requires_video
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


@requires_video
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


@requires_video
async def test_recording_watchdog_path_properties(browser_session: BrowserSession, page_url: str, tmp_path: Path):
	"""Test that RecordingWatchdog exposes active and final recording paths correctly."""
	watchdog = browser_session._recording_watchdog
	assert watchdog is not None

	# Before recording starts
	assert not watchdog.is_recording
	assert watchdog.recording_path is None
	assert browser_session.recording_path is None

	out_path = tmp_path / 'props_test.mp4'
	saved = await watchdog.start_recording(out_path)
	assert saved == out_path

	# During recording
	assert watchdog.is_recording
	assert watchdog.recording_path == out_path
	assert browser_session.recording_path == out_path

	await _drive_browser_briefly(browser_session, page_url)

	final = await watchdog.stop_recording()
	assert final == out_path

	# After recording stops
	assert not watchdog.is_recording
	assert watchdog.recording_path == out_path
	assert browser_session.recording_path == out_path
	assert out_path.exists()
	assert out_path.stat().st_size > 0


async def test_agent_history_video_path_disabled(page_url: str):
	"""When recording is disabled, history.video_path is None."""
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	agent = Agent(
		task=f'go to {page_url}',
		llm=create_mock_llm(),
		browser_session=browser_session,
	)
	history = await agent.run(max_steps=1)

	assert history.video_path is None
	dumped = history.model_dump()
	assert dumped['video_path'] is None


@requires_video
async def test_agent_history_video_path_enabled(page_url: str, tmp_path: Path):
	"""When recording is enabled, history.video_path contains the finalized recording path."""
	video_dir = tmp_path / 'agent_videos'
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, record_video_dir=video_dir),
	)
	agent = Agent(
		task=f'go to {page_url}',
		llm=create_mock_llm(),
		browser_session=browser_session,
	)
	history = await agent.run(max_steps=1)

	# 1. history.video_path is not None
	assert history.video_path is not None
	video_file = Path(history.video_path)

	# 2. The file exists and is non-empty
	assert video_file.exists(), f'Recording file {video_file} should exist on disk'
	assert video_file.stat().st_size > 0, f'Recording file {video_file} should not be empty'
	assert video_file.parent.resolve() == video_dir.resolve()

	# 3. Matches watchdog's recorded path and actual file on disk
	assert browser_session.recording_path is not None
	assert history.video_path == str(browser_session.recording_path)
	recorded_files = list(video_dir.glob('*.mp4'))
	assert len(recorded_files) == 1
	assert Path(history.video_path).resolve() == recorded_files[0].resolve()

	# 4. Serialization matches history.video_path
	dumped = history.model_dump()
	assert dumped['video_path'] == history.video_path


async def test_agent_history_video_path_serialization_and_redaction(tmp_path: Path):
	"""Test AgentHistoryList video_path validation, serialization, and sensitive data redaction."""
	# Test video_path assignment and serialization
	sample_path = tmp_path / 'secret_user_dir' / 'rec.mp4'
	history_with_path = AgentHistoryList(history=[], video_path=str(sample_path))
	assert isinstance(history_with_path.video_path, str)
	assert history_with_path.video_path == str(sample_path)

	# Test model_dump without sensitive data
	dump = history_with_path.model_dump()
	assert dump['video_path'] == str(sample_path)

	# Test model_dump with sensitive data redaction
	sensitive_data: dict[str, str | dict[str, str]] = {'secret': 'secret_user_dir'}
	dump_redacted = history_with_path.model_dump(sensitive_data=sensitive_data)
	assert 'secret_user_dir' not in dump_redacted['video_path']
	assert '<secret>' in dump_redacted['video_path']

	# Test roundtrip via load_from_dict and save_to_file / load_from_file
	loaded = AgentHistoryList.load_from_dict(dump, AgentOutput)
	assert loaded.video_path == str(sample_path)

	json_file = tmp_path / 'history.json'
	history_with_path.save_to_file(json_file)
	loaded_from_file = AgentHistoryList.load_from_file(json_file, AgentOutput)
	assert loaded_from_file.video_path == str(sample_path)

	# Test exclude_none
	empty_history = AgentHistoryList(history=[])
	assert empty_history.model_dump()['video_path'] is None
	assert 'video_path' not in empty_history.model_dump(exclude_none=True)


async def test_agent_history_video_path_failed_recording_degrades_gracefully(tmp_path: Path, monkeypatch):
	"""If recording initialization fails, history.video_path remains None without crashing."""
	from browser_use.browser.watchdogs import recording_watchdog as rw_mod

	async def fake_start_recording(self: Any, *_args: Any, **_kwargs: Any) -> Path:
		raise RuntimeError('simulated recorder failure')

	monkeypatch.setattr(rw_mod.RecordingWatchdog, 'start_recording', fake_start_recording)

	browser_session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, record_video_dir=tmp_path),
	)
	agent = Agent(
		task='test graceful degradation',
		llm=create_mock_llm(),
		browser_session=browser_session,
	)
	history = await agent.run(max_steps=1)

	assert history.video_path is None
	assert history.model_dump()['video_path'] is None


@requires_video
async def test_agent_history_video_path_keep_alive(page_url: str, tmp_path: Path):
	"""When keep_alive=True, history.video_path is still populated with finalized path after close()."""
	video_dir = tmp_path / 'keep_alive_videos'
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, keep_alive=True, record_video_dir=video_dir),
	)
	agent = Agent(
		task=f'go to {page_url}',
		llm=create_mock_llm(),
		browser_session=browser_session,
	)
	try:
		history = await agent.run(max_steps=1)

		# 1. history.video_path is not None
		assert history.video_path is not None
		video_file = Path(history.video_path)

		# 2. The file exists and is non-empty
		assert video_file.exists(), f'Recording file {video_file} should exist on disk'
		assert video_file.stat().st_size > 0, f'Recording file {video_file} should not be empty'
		assert video_file.parent.resolve() == video_dir.resolve()

		# 3. Matches the session's finalized path and the file on disk
		assert browser_session.recording_path is not None
		assert history.video_path == str(browser_session.recording_path)
		recorded_files = list(video_dir.glob('*.mp4'))
		assert len(recorded_files) == 1
		assert Path(history.video_path).resolve() == recorded_files[0].resolve()
	finally:
		await browser_session.kill()


@requires_video
async def test_keep_alive_session_reuse_separate_recordings(page_url: str, tmp_path: Path):
	"""Regression test: two Agent runs on the SAME keep_alive BrowserSession produce separate recordings.

	Verifies:
	- Both histories have a non-None video_path
	- Paths are different
	- Both files exist
	- Both files are non-empty
	- Second history does not contain the first recording path
	"""
	video_dir = tmp_path / 'reuse_videos'
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, keep_alive=True, record_video_dir=video_dir),
	)

	try:
		# ── Agent 1 ──
		agent1 = Agent(
			task=f'go to {page_url}',
			llm=create_mock_llm(),
			browser_session=browser_session,
		)
		history1 = await agent1.run(max_steps=1)

		# ── Agent 2 (same BrowserSession) ──
		agent2 = Agent(
			task=f'go to {page_url}',
			llm=create_mock_llm(),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=1)

		# 1. Both histories have a non-None video_path
		assert history1.video_path is not None, 'Agent 1 history should have a video_path'
		assert history2.video_path is not None, 'Agent 2 history should have a video_path'

		# 2. Paths are different
		assert history1.video_path != history2.video_path, (
			f'Agent 1 and Agent 2 should have different video paths, got {history1.video_path} for both'
		)

		# 3. Both files exist
		path1 = Path(history1.video_path)
		path2 = Path(history2.video_path)
		assert path1.exists(), f'Agent 1 video file {path1} should exist'
		assert path2.exists(), f'Agent 2 video file {path2} should exist'

		# 4. Both files are non-empty
		assert path1.stat().st_size > 0, f'Agent 1 video file {path1} should not be empty'
		assert path2.stat().st_size > 0, f'Agent 2 video file {path2} should not be empty'

		# Verify both are in the expected directory
		assert path1.parent.resolve() == video_dir.resolve()
		assert path2.parent.resolve() == video_dir.resolve()

		# Verify we have exactly 2 recording files
		all_videos = list(video_dir.glob('*.mp4'))
		assert len(all_videos) == 2, f'Expected 2 video files, found {len(all_videos)}: {all_videos}'
	finally:
		await browser_session.kill()


@requires_video
async def test_keep_alive_failed_reuse_does_not_reuse_previous_recording(
	page_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
	"""A failed Agent 2 startup must not expose Agent 1's finalized recording path."""
	video_dir = tmp_path / 'failed_reuse_videos'
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, keep_alive=True, record_video_dir=video_dir),
	)

	try:
		first_agent = Agent(
			task=f'go to {page_url}',
			llm=create_mock_llm(),
			browser_session=browser_session,
		)
		first_history = await first_agent.run(max_steps=1)
		assert first_history.video_path is not None
		first_path = Path(first_history.video_path)
		assert first_path.exists()
		assert first_path.stat().st_size > 0

		second_agent = Agent(
			task=f'go to {page_url}',
			llm=create_mock_llm(),
			browser_session=browser_session,
		)
		startup_failures = 0

		async def fail_browser_start(_event: Any) -> None:
			nonlocal startup_failures
			startup_failures += 1
			raise RuntimeError('simulated BrowserStartEvent failure')

		original_handlers = browser_session.event_bus.handlers['BrowserStartEvent']
		monkeypatch.setitem(browser_session.event_bus.handlers, 'BrowserStartEvent', [fail_browser_start])
		try:
			with pytest.raises(RuntimeError, match='simulated BrowserStartEvent failure'):
				await second_agent.run(max_steps=1)
		finally:
			browser_session.event_bus.handlers['BrowserStartEvent'] = original_handlers

		second_history = second_agent.history
		assert startup_failures == 1
		assert second_history.video_path is None
		assert first_history.video_path == str(first_path)
		assert first_path.exists()
		assert first_path.stat().st_size > 0
	finally:
		await browser_session.kill()


@requires_video
async def test_reset_finalizes_active_recording(browser_session: BrowserSession, page_url: str, tmp_path: Path):
	"""Regression test: reset() must finalize an active recording before discarding the watchdog."""
	watchdog = browser_session._recording_watchdog
	assert watchdog is not None

	out_path = tmp_path / 'reset_test.mp4'
	await watchdog.start_recording(out_path)
	assert watchdog.is_recording

	await _drive_browser_briefly(browser_session, page_url)

	# reset() should finalize the recording, not silently drop it
	await browser_session.reset()

	# After reset, the recording file should exist and be non-empty
	assert out_path.exists(), 'Recording should be finalized before reset discards watchdog'
	assert out_path.stat().st_size > 0, 'Finalized recording should be non-empty'

	# The session should have preserved the recording path
	assert browser_session.recording_path == out_path


async def test_stop_recording_discards_partial_file_when_finalization_fails(browser_session: BrowserSession, tmp_path: Path):
	"""An existing partial file is not reported when the recorder failed to finalize."""
	from typing import cast

	from browser_use.browser.video_recorder import VideoRecorderService

	class FailingWriter:
		def close(self) -> None:
			raise OSError('simulated encoder finalization failure')

	watchdog = browser_session._recording_watchdog
	assert watchdog is not None

	# Keep a non-empty partial/stale file in place to prove exists() alone is insufficient.
	partial_path = tmp_path / 'partial.mp4'
	partial_path.write_bytes(b'partial recording')
	recorder = VideoRecorderService(
		output_path=partial_path,
		size=ViewportSize(width=16, height=16),
		framerate=10,
	)
	recorder._writer = cast(Any, FailingWriter())
	recorder._is_active = True
	watchdog._recorder = recorder

	assert await watchdog.stop_recording() is None
	assert watchdog.recording_path is None
	assert browser_session.recording_path is None
	assert partial_path.exists() and partial_path.stat().st_size > 0
