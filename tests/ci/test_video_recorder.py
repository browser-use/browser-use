from pathlib import Path

from browser_use.browser.profile import ViewportSize
from browser_use.browser.video_recorder import VideoRecorderService
from browser_use.browser.watchdogs.recording_watchdog import _get_screencast_frame_timestamp


class FakeWriter:
	def __init__(self) -> None:
		self.frames: list[str] = []

	def append_data(self, frame: str) -> None:
		self.frames.append(frame)


def create_recorder(framerate: int = 10) -> VideoRecorderService:
	return VideoRecorderService(
		output_path=Path('test.mp4'),
		size=ViewportSize(width=16, height=16),
		framerate=framerate,
	)


def test_frame_write_plan_repeats_previous_frame_for_slow_screencast_frames():
	recorder = create_recorder(framerate=10)

	assert recorder._get_frame_write_plan(0.0) == (0, 1)

	# A 500ms gap at 10fps covers 5 frame intervals. The already-written
	# previous frame covers the first interval, then the current frame is written.
	assert recorder._get_frame_write_plan(0.5) == (4, 1)


def test_frame_write_plan_accumulates_fast_screencast_frames():
	recorder = create_recorder(framerate=10)

	assert recorder._get_frame_write_plan(0.0) == (0, 1)
	assert recorder._get_frame_write_plan(0.04) == (0, 0)
	assert recorder._get_frame_write_plan(0.1) == (0, 1)


def test_frame_write_plan_resets_when_timestamp_source_changes():
	recorder = create_recorder(framerate=10)

	assert recorder._get_frame_write_plan(100.0, 'cdp') == (0, 1)
	assert recorder._get_frame_write_plan(0.0, 'local') == (0, 1)


def test_append_timed_frame_writes_duplicate_frames_to_preserve_elapsed_time():
	recorder = create_recorder(framerate=10)
	writer = FakeWriter()
	recorder._writer = writer  # type: ignore[assignment]

	times = iter([0.0, 0.5])
	recorder._time_func = lambda: next(times)

	recorder._append_timed_frame('first')
	recorder._append_timed_frame('second')

	assert writer.frames == ['first', 'first', 'first', 'first', 'first', 'second']


def test_append_timed_frame_uses_cdp_timestamps_when_provided():
	recorder = create_recorder(framerate=10)
	writer = FakeWriter()
	recorder._writer = writer  # type: ignore[assignment]
	recorder._time_func = lambda: (_ for _ in ()).throw(AssertionError('local clock should not be used'))

	recorder._append_timed_frame('first', timestamp=100.0)
	recorder._append_timed_frame('second', timestamp=100.5)

	assert writer.frames == ['first', 'first', 'first', 'first', 'first', 'second']


def test_append_timed_frame_skips_sub_frame_interval_updates():
	recorder = create_recorder(framerate=10)
	writer = FakeWriter()
	recorder._writer = writer  # type: ignore[assignment]

	times = iter([0.0, 0.04, 0.1])
	recorder._time_func = lambda: next(times)

	recorder._append_timed_frame('first')
	recorder._append_timed_frame('too-fast')
	recorder._append_timed_frame('next-frame')

	assert writer.frames == ['first', 'next-frame']


def test_screencast_frame_timestamp_is_read_from_metadata():
	assert (
		_get_screencast_frame_timestamp(
			{
				'data': 'frame',
				'metadata': {
					'offsetTop': 0.0,
					'pageScaleFactor': 1.0,
					'deviceWidth': 16.0,
					'deviceHeight': 16.0,
					'scrollOffsetX': 0.0,
					'scrollOffsetY': 0.0,
					'timestamp': 123.25,
				},
				'sessionId': 1,
			}
		)
		== 123.25
	)
