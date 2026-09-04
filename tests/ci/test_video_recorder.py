from pathlib import Path
from typing import Any

import pytest

from browser_use.browser.profile import ViewportSize
from browser_use.browser.video_recorder import VideoRecorderService


class FakeWriter:
	def __init__(self) -> None:
		self.frames: list[Any] = []
		self.closed = False

	def append_data(self, frame: Any) -> None:
		self.frames.append(frame)

	def close(self) -> None:
		self.closed = True


def _recorder_with_fake_writer(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path, framerate: int
) -> tuple[VideoRecorderService, FakeWriter]:
	writer = FakeWriter()
	recorder = VideoRecorderService(
		output_path=tmp_path / 'recording.mp4',
		size=ViewportSize(width=2, height=2),
		framerate=framerate,
	)
	recorder._writer = writer  # type: ignore[assignment]
	recorder._is_active = True
	decoded_frames = iter(['first-frame', 'second-frame'])
	monkeypatch.setattr(recorder, '_decode_frame', lambda _frame_data: next(decoded_frames))
	return recorder, writer


def test_add_frame_repeats_previous_frame_for_timestamp_gap(
	monkeypatch: pytest.MonkeyPatch,
	tmp_path: Path,
) -> None:
	recorder, writer = _recorder_with_fake_writer(monkeypatch, tmp_path, framerate=10)

	recorder.add_frame('frame-data', timestamp=100.0)
	recorder.add_frame('frame-data', timestamp=100.5)

	assert writer.frames == ['first-frame', 'first-frame', 'first-frame', 'first-frame', 'first-frame', 'second-frame']


def test_add_frame_without_timestamps_does_not_repeat_frames(
	monkeypatch: pytest.MonkeyPatch,
	tmp_path: Path,
) -> None:
	recorder, writer = _recorder_with_fake_writer(monkeypatch, tmp_path, framerate=10)

	recorder.add_frame('frame-data')
	recorder.add_frame('frame-data')

	assert writer.frames == ['first-frame', 'second-frame']


def test_non_monotonic_timestamps_do_not_repeat_frames(
	monkeypatch: pytest.MonkeyPatch,
	tmp_path: Path,
) -> None:
	recorder, writer = _recorder_with_fake_writer(monkeypatch, tmp_path, framerate=10)

	recorder.add_frame('frame-data', timestamp=100.0)
	recorder.add_frame('frame-data', timestamp=99.0)

	assert writer.frames == ['first-frame', 'second-frame']
