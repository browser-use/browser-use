"""Test recording_path exposure in BrowserStateHistory and AgentHistoryList."""

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList
from browser_use.browser.views import BrowserStateHistory


def _make_history_item(recording_path: str | None = None, screenshot_path: str | None = None) -> AgentHistory:
	return AgentHistory(
		model_output=None,
		result=[ActionResult(extracted_content='test')],
		state=BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
			screenshot_path=screenshot_path,
			recording_path=recording_path,
		),
	)


class TestRecordingPathInBrowserStateHistory:
	def test_recording_path_defaults_to_none(self):
		state = BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
		)
		assert state.recording_path is None

	def test_recording_path_stored(self):
		state = BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
			recording_path='/tmp/video.mp4',
		)
		assert state.recording_path == '/tmp/video.mp4'

	def test_to_dict_includes_recording_path(self):
		state = BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
			recording_path='/tmp/video.mp4',
		)
		d = state.to_dict()
		assert 'recording_path' in d
		assert d['recording_path'] == '/tmp/video.mp4'

	def test_to_dict_recording_path_none(self):
		state = BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
		)
		d = state.to_dict()
		assert 'recording_path' in d
		assert d['recording_path'] is None


class TestRecordingPathsInAgentHistoryList:
	def test_recording_paths_all_set(self):
		history = AgentHistoryList(
			history=[
				_make_history_item(recording_path='/tmp/video.mp4'),
				_make_history_item(recording_path='/tmp/video.mp4'),
			]
		)
		paths = history.recording_paths()
		assert paths == ['/tmp/video.mp4', '/tmp/video.mp4']

	def test_recording_paths_none_when_disabled(self):
		history = AgentHistoryList(
			history=[
				_make_history_item(),
				_make_history_item(),
			]
		)
		paths = history.recording_paths()
		assert paths == [None, None]

	def test_recording_paths_n_last(self):
		history = AgentHistoryList(
			history=[
				_make_history_item(recording_path='/tmp/video.mp4'),
				_make_history_item(recording_path='/tmp/video.mp4'),
				_make_history_item(recording_path='/tmp/video.mp4'),
			]
		)
		paths = history.recording_paths(n_last=2)
		assert len(paths) == 2

	def test_recording_paths_filter_none(self):
		history = AgentHistoryList(
			history=[
				_make_history_item(),
				_make_history_item(recording_path='/tmp/video.mp4'),
			]
		)
		paths = history.recording_paths(return_none_if_not_recording=False)
		assert paths == ['/tmp/video.mp4']

	def test_recording_paths_empty(self):
		history = AgentHistoryList(history=[])
		assert history.recording_paths() == []

	def test_recording_paths_n_last_zero(self):
		history = AgentHistoryList(history=[_make_history_item(recording_path='/tmp/video.mp4')])
		assert history.recording_paths(n_last=0) == []

	def test_serialization_roundtrip(self):
		"""Verify recording_path survives model_dump / model_validate."""
		history = AgentHistoryList(
			history=[
				_make_history_item(recording_path='/tmp/video.mp4', screenshot_path='/tmp/step_0.png'),
			]
		)
		data = history.model_dump()
		restored = AgentHistoryList.model_validate(data)
		assert restored.history[0].state.recording_path == '/tmp/video.mp4'
		assert restored.history[0].state.screenshot_path == '/tmp/step_0.png'
