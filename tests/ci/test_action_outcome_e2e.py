"""E2E tests for ActionOutcome in tools/service.py action handlers.

Tests use mocked BrowserSession - no real browser needed.
"""

from unittest.mock import MagicMock

from browser_use.agent.views import ActionOutcome
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools


def _mock_session(**kw):
	s = MagicMock()
	s.event_bus = MagicMock()
	s.logger = MagicMock()

	async def _dispatch(event):
		class A:
			def __await__(self):
				async def _inner():
					return None

				return _inner().__await__()

			async def event_result(self, **kw):
				return None

		return A()

	s.event_bus.dispatch = _dispatch
	for k, v in kw.items():
		setattr(s, k, v)
	return s


def _action(tools, name, params):
	"""Create an ActionModel with **unpacking to avoid IDE warnings on dynamic fields."""
	M = tools.registry.create_action_model()
	return M(**{name: params})


class TestSearchOutcome:
	async def test_unsupported_engine_is_invalid_state(self):
		t = Tools()
		r = await t.act(action=_action(t, 'search', {'query': 'x', 'engine': 'yahoo'}), browser_session=_mock_session())
		assert r.outcome == ActionOutcome.INVALID_STATE
		assert r.error is not None and 'Unsupported search engine' in r.error


class TestNavigateOutcome:
	async def test_failure_is_system_error(self):
		t = Tools()

		async def raise_(event):
			raise RuntimeError('Connection refused')

		s = _mock_session(event_bus=MagicMock(dispatch=raise_))
		r = await t.act(action=_action(t, 'navigate', {'url': 'https://example.com'}), browser_session=s)
		assert r.outcome == ActionOutcome.SYSTEM_ERROR
		assert r.error is not None and 'Navigation failed' in r.error


class TestInputOutcome:
	async def test_missing_element_is_not_found(self):
		t = Tools()
		s = _mock_session()

		async def get(idx):
			return None

		s.get_element_by_index = get
		r = await t.act(action=_action(t, 'input', {'index': 999, 'text': 'hi'}), browser_session=s)
		assert r.outcome == ActionOutcome.NOT_FOUND
		assert r.extracted_content is not None and 'not available' in r.extracted_content


class TestScrollOutcome:
	async def test_missing_element_is_not_found(self):
		t = Tools()
		s = _mock_session()

		async def get(idx):
			return None

		s.get_element_by_index = get

		async def state(**kw):
			from browser_use.browser.views import BrowserStateSummary
			from browser_use.dom.views import SerializedDOMState

			return BrowserStateSummary(
				dom_state=SerializedDOMState(_root=None, selector_map={}), url='https://ex.com', title='', tabs=[]
			)

		s.get_browser_state_summary = state
		r = await t.act(action=_action(t, 'scroll', {'down': True, 'pages': 1, 'index': 999}), browser_session=s)
		assert r.outcome == ActionOutcome.NOT_FOUND
		assert r.error is not None and 'not found' in r.error


class TestDoneOutcome:
	async def test_success(self):
		t = Tools()
		r = await t.act(
			action=_action(t, 'done', {'text': 'ok', 'success': True}),
			browser_session=_mock_session(),
			file_system=FileSystem(base_dir='/tmp/test_fs'),
		)
		assert r.is_done
		assert r.outcome == ActionOutcome.SUCCESS

	async def test_failure_flag(self):
		t = Tools()
		r = await t.act(
			action=_action(t, 'done', {'text': 'no', 'success': False}),
			browser_session=_mock_session(),
			file_system=FileSystem(base_dir='/tmp/test_fs'),
		)
		assert r.is_done
		assert r.outcome == ActionOutcome.SUCCESS
		assert r.success is False


class TestClickOutcome:
	"""click action: missing coords → INVALID_STATE, element not found → NOT_FOUND"""

	async def test_missing_coords_is_invalid_state(self):
		t = Tools()
		t.set_coordinate_clicking(True)
		r = await t.act(
			action=_action(t, 'click', {'index': None, 'coordinate_x': None, 'coordinate_y': None}),
			browser_session=_mock_session(),
		)
		assert r.outcome == ActionOutcome.INVALID_STATE
		assert r.error is not None and 'Must provide either index or both coordinate_x and coordinate_y' in r.error

	async def test_missing_element_is_not_found(self):
		t = Tools()
		s = _mock_session()

		async def get(idx):
			return None

		s.get_element_by_index = get

		async def tabs():
			return []

		s.get_tabs = tabs
		r = await t.act(
			action=_action(t, 'click', {'index': 999, 'coordinate_x': None, 'coordinate_y': None}),
			browser_session=s,
		)
		assert r.outcome == ActionOutcome.NOT_FOUND
		assert r.extracted_content is not None and 'not available' in r.extracted_content
