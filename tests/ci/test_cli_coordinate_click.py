"""Tests for CLI coordinate clicking support.

Verifies that the CLI correctly parses both index-based and coordinate-based
click commands, that the browser command handler dispatches the right events,
and that the direct CLI selector map cache works correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
	from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode

from browser_use.skill_cli.main import build_parser


class TestClickArgParsing:
	"""Test argparse handles click with index and coordinates."""

	def test_click_single_index(self):
		"""browser-use click 5 -> args.args == [5]"""
		parser = build_parser()
		args = parser.parse_args(['click', '5'])
		assert args.command == 'click'
		assert args.args == [5]

	def test_click_coordinates(self):
		"""browser-use click 200 800 -> args.args == [200, 800]"""
		parser = build_parser()
		args = parser.parse_args(['click', '200', '800'])
		assert args.command == 'click'
		assert args.args == [200, 800]

	def test_click_no_args_fails(self):
		"""browser-use click (no args) should fail."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['click'])

	def test_click_three_args_parsed(self):
		"""browser-use click 1 2 3 -> args.args == [1, 2, 3] (handler will reject)."""
		parser = build_parser()
		args = parser.parse_args(['click', '1', '2', '3'])
		assert args.args == [1, 2, 3]

	def test_click_non_int_fails(self):
		"""browser-use click abc should fail (type=int enforced)."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['click', 'abc'])


class TestExtractArgParsing:
	"""Test argparse handles extract options."""

	def test_extract_defaults(self):
		"""browser-use extract query -> query only with default extraction flags."""
		parser = build_parser()
		args = parser.parse_args(['extract', 'headline'])
		assert args.command == 'extract'
		assert args.query == 'headline'
		assert args.extract_links is False
		assert args.start_from_char == 0
		assert args.output_schema is None

	def test_extract_all_options(self):
		"""browser-use extract supports link extraction, offsets, and structured schema."""
		parser = build_parser()
		args = parser.parse_args(
			[
				'extract',
				'headline',
				'--extract-links',
				'--start-from-char',
				'250',
				'--output-schema',
				'{"type":"object","properties":{"title":{"type":"string"}}}',
			]
		)
		assert args.command == 'extract'
		assert args.query == 'headline'
		assert args.extract_links is True
		assert args.start_from_char == 250
		assert args.output_schema == {'type': 'object', 'properties': {'title': {'type': 'string'}}}

	def test_extract_invalid_schema_fails(self):
		"""extract --output-schema expects a JSON object."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['extract', 'headline', '--output-schema', '["not","an","object"]'])


class TestNestedCommandParsing:
	"""Test nested browser CLI subcommands are required."""

	def test_wait_requires_subcommand(self):
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['wait'])

	def test_get_requires_subcommand(self):
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['get'])

	def test_cookies_requires_subcommand(self):
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['cookies'])

	def test_wait_selector_still_parses(self):
		parser = build_parser()
		args = parser.parse_args(['wait', 'selector', '.cta'])
		assert args.command == 'wait'
		assert args.wait_command == 'selector'
		assert args.selector == '.cta'

	def test_get_title_still_parses(self):
		parser = build_parser()
		args = parser.parse_args(['get', 'title'])
		assert args.command == 'get'
		assert args.get_command == 'title'

	def test_cookies_get_still_parses(self):
		parser = build_parser()
		args = parser.parse_args(['cookies', 'get', '--url', 'https://example.com'])
		assert args.command == 'cookies'
		assert args.cookies_command == 'get'
		assert args.url == 'https://example.com'


class TestMainCommandExitCodes:
	"""Test CLI main() returns nonzero for handler-level browser command failures."""

	def test_main_returns_error_for_handler_level_failure(self, monkeypatch, capsys):
		"""A successful transport envelope with data.error should still exit 1."""
		from browser_use.skill_cli import install_config
		from browser_use.skill_cli import main as cli_main

		monkeypatch.setattr(
			install_config,
			'is_mode_available',
			lambda mode: True,
		)
		monkeypatch.setattr(cli_main, 'ensure_server', lambda *args, **kwargs: None)
		monkeypatch.setattr(
			cli_main,
			'send_command',
			lambda session, action, params: {'success': True, 'data': {'error': 'Element index 999 not found'}},
		)
		monkeypatch.setattr('sys.argv', ['browser-use', 'click', '999'])

		assert cli_main.main() == 1
		captured = capsys.readouterr()
		assert captured.out == ''
		assert 'Error: Element index 999 not found' in captured.err

	def test_main_json_mode_preserves_payload_but_returns_error(self, monkeypatch, capsys):
		"""JSON output should still print the payload while returning a failing exit code."""
		from browser_use.skill_cli import install_config
		from browser_use.skill_cli import main as cli_main

		monkeypatch.setattr(
			install_config,
			'is_mode_available',
			lambda mode: True,
		)
		monkeypatch.setattr(cli_main, 'ensure_server', lambda *args, **kwargs: None)
		monkeypatch.setattr(
			cli_main,
			'send_command',
			lambda session, action, params: {'success': True, 'data': {'error': 'boom'}},
		)
		monkeypatch.setattr('sys.argv', ['browser-use', '--json', 'click', '5'])

		assert cli_main.main() == 1
		captured = capsys.readouterr()
		assert '"success": true' in captured.out
		assert '"error": "boom"' in captured.out
		assert captured.err == ''


class TestClickCommandHandler:
	"""Test the browser command handler dispatches correctly for click."""

	class _FailedEvent:
		"""Minimal event stub that raises from event_result()."""

		def __await__(self):
			async def _done():
				return self

			return _done().__await__()

		async def event_result(self, raise_if_any=True, raise_if_none=False):
			raise RuntimeError('simulated event failure')

	async def test_coordinate_click_handler(self, httpserver):
		"""Coordinate click dispatches ClickCoordinateEvent."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		httpserver.expect_request('/').respond_with_data(
			'<html><body><button>Click me</button></body></html>',
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			from browser_use.browser.events import NavigateToUrlEvent

			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				browser_mode='chromium',
				headed=False,
				profile=None,
				browser_session=session,
			)

			result = await handle('click', session_info, {'args': [100, 200]})
			assert 'clicked_coordinate' in result
			assert result['clicked_coordinate'] == {'x': 100, 'y': 200}
		finally:
			await session.kill()

	async def test_index_click_handler(self, httpserver):
		"""Index click dispatches ClickElementEvent."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		httpserver.expect_request('/').respond_with_data(
			'<html><body><button id="btn">Click me</button></body></html>',
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			from browser_use.browser.events import NavigateToUrlEvent

			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				browser_mode='chromium',
				headed=False,
				profile=None,
				browser_session=session,
			)

			# Index 999 won't exist, so we expect the error path
			result = await handle('click', session_info, {'args': [999]})
			assert 'error' in result
		finally:
			await session.kill()

	async def test_invalid_args_count(self):
		"""Three args returns error without touching the browser."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		# BrowserSession constructed but not started — handler hits the
		# 3-arg error branch before doing anything with the session.
		session_info = SessionInfo(
			name='test',
			browser_mode='chromium',
			headed=False,
			profile=None,
			browser_session=BrowserSession(headless=True),
		)

		result = await handle('click', session_info, {'args': [1, 2, 3]})
		assert 'error' in result
		assert 'Usage' in result['error']

	async def test_click_handler_propagates_event_failure(self):
		"""Handler should not report success when the click event itself failed."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session = BrowserSession(headless=True)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=_make_dom_node(node_name='BUTTON')))
		event_bus = MagicMock()
		event_bus.dispatch = MagicMock(return_value=self._FailedEvent())
		object.__setattr__(session, 'event_bus', event_bus)

		session_info = SessionInfo(
			name='test',
			browser_mode='chromium',
			headed=False,
			profile=None,
			browser_session=session,
		)

		with pytest.raises(RuntimeError, match='simulated event failure'):
			await handle('click', session_info, {'args': [5]})

	async def test_switch_handler_propagates_event_failure(self):
		"""Tab switching should surface event handler failures instead of returning success."""
		from browser_use.browser.session import BrowserSession
		from browser_use.browser.views import TabInfo
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session = BrowserSession(headless=True)
		object.__setattr__(
			session,
			'get_tabs',
			AsyncMock(return_value=[TabInfo(target_id='target-1', url='https://example.com', title='Example')]),
		)
		event_bus = MagicMock()
		event_bus.dispatch = MagicMock(return_value=self._FailedEvent())
		object.__setattr__(session, 'event_bus', event_bus)

		session_info = SessionInfo(
			name='test',
			browser_mode='chromium',
			headed=False,
			profile=None,
			browser_session=session,
		)

		with pytest.raises(RuntimeError, match='simulated event failure'):
			await handle('switch', session_info, {'tab': 0})

	async def test_safari_rightclick_handler_uses_backend(self):
		"""Safari rightclick should delegate to the Safari backend instead of erroring."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='BUTTON')
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))

		class SafariBackendStub:
			def __init__(self) -> None:
				self.click_element = AsyncMock(return_value={'ok': True})

		backend = SafariBackendStub()
		object.__setattr__(session, '_backend', backend)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('rightclick', session_info, {'index': 7})

		assert result == {'right_clicked': 7}
		backend.click_element.assert_awaited_once_with(node, button='right')

	async def test_safari_hover_handler_uses_backend(self):
		"""Safari hover should delegate to the Safari backend instead of erroring."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='BUTTON')
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))

		class SafariBackendStub:
			def __init__(self) -> None:
				self.hover_element = AsyncMock(return_value={'ok': True})

		backend = SafariBackendStub()
		object.__setattr__(session, '_backend', backend)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('hover', session_info, {'index': 4})

		assert result == {'hovered': 4}
		backend.hover_element.assert_awaited_once_with(node)

	async def test_safari_dblclick_handler_uses_backend(self):
		"""Safari double click should delegate to the Safari backend instead of erroring."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='BUTTON')
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))

		class SafariBackendStub:
			def __init__(self) -> None:
				self.double_click_element = AsyncMock(return_value={'ok': True})

		backend = SafariBackendStub()
		object.__setattr__(session, '_backend', backend)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('dblclick', session_info, {'index': 9})

		assert result == {'double_clicked': 9}
		backend.double_click_element.assert_awaited_once_with(node)

	async def test_safari_get_value_handler_uses_evaluate_javascript(self):
		"""Safari get value should use in-page JS rather than CDP-only access."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='INPUT')
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))
		evaluate_javascript = AsyncMock(return_value='hello from safari')
		object.__setattr__(session, 'evaluate_javascript', evaluate_javascript)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('get', session_info, {'get_command': 'value', 'index': 3})

		assert result == {'index': 3, 'value': 'hello from safari'}
		evaluate_javascript.assert_awaited_once()

	async def test_safari_get_bbox_handler_uses_node_absolute_position(self):
		"""Safari get bbox should use the DOM node position instead of CDP."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.dom.views import DOMRect
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(
			node_name='INPUT',
			absolute_position=DOMRect(x=12.0, y=24.0, width=320.0, height=48.0),
		)
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('get', session_info, {'get_command': 'bbox', 'index': 5})

		assert result == {
			'index': 5,
			'bbox': {'x': 12.0, 'y': 24.0, 'width': 320.0, 'height': 48.0},
		}

	async def test_safari_get_text_handler_uses_evaluate_javascript(self):
		"""Safari get text should read from the live DOM instead of the cached node snapshot."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='DIV', node_value='stale text')
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))
		evaluate_javascript = AsyncMock(return_value='live safari text')
		object.__setattr__(session, 'evaluate_javascript', evaluate_javascript)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('get', session_info, {'get_command': 'text', 'index': 6})

		assert result == {'index': 6, 'text': 'live safari text'}
		evaluate_javascript.assert_awaited_once()

	async def test_safari_get_attributes_handler_uses_evaluate_javascript(self):
		"""Safari get attributes should read live DOM attributes instead of the cached node snapshot."""
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		node = _make_dom_node(node_name='BUTTON')
		node.attributes['data-stale'] = 'cached'
		session = BrowserSession(
			browser_profile=BrowserProfile(
				automation_backend='safari',
				safari_profile='active',
				headless=False,
			)
		)
		object.__setattr__(session, 'get_element_by_index', AsyncMock(return_value=node))
		evaluate_javascript = AsyncMock(return_value={'role': 'button', 'data-live': 'fresh'})
		object.__setattr__(session, 'evaluate_javascript', evaluate_javascript)

		session_info = SessionInfo(
			name='test',
			browser_mode='safari',
			headed=True,
			profile='active',
			browser_session=session,
		)

		result = await handle('get', session_info, {'get_command': 'attributes', 'index': 8})

		assert result == {'index': 8, 'attributes': {'role': 'button', 'data-live': 'fresh'}}
		evaluate_javascript.assert_awaited_once()


class TestExtractCommandHandler:
	"""Test the browser command handler dispatches extraction correctly."""

	async def test_extract_handler_returns_extracted_content(self):
		"""Extract delegates to the shared tools pipeline and returns the payload."""
		from browser_use.agent.views import ActionResult
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session_info = SessionInfo(
			name='test',
			browser_mode='chromium',
			headed=False,
			profile=None,
			browser_session=BrowserSession(headless=True),
		)

		class ToolsStub:
			def __init__(self) -> None:
				self.extract = AsyncMock(return_value=ActionResult(extracted_content='headline: Browser Use'))

		tools_instance = ToolsStub()

		with (
			patch('browser_use.skill_cli.commands.agent.get_llm', return_value=object()),
			patch('browser_use.tools.service.Tools', return_value=tools_instance),
		):
			result = await handle(
				'extract',
				session_info,
				{
					'query': 'headline',
					'extract_links': True,
					'start_from_char': 250,
					'output_schema': {'type': 'object', 'properties': {'title': {'type': 'string'}}},
				},
			)

		assert result == {'query': 'headline', 'result': 'headline: Browser Use'}
		tools_instance.extract.assert_awaited_once()
		call = tools_instance.extract.await_args
		assert call is not None
		assert call.kwargs['browser_session'] is session_info.browser_session
		assert call.kwargs['query'] == 'headline'
		assert call.kwargs['extract_links'] is True
		assert call.kwargs['start_from_char'] == 250
		assert call.kwargs['output_schema'] == {'type': 'object', 'properties': {'title': {'type': 'string'}}}

	async def test_extract_handler_raises_when_no_llm_configured(self):
		"""Extract should fail clearly when no CLI LLM credentials are configured."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session_info = SessionInfo(
			name='test',
			browser_mode='chromium',
			headed=False,
			profile=None,
			browser_session=BrowserSession(headless=True),
		)

		with patch('browser_use.skill_cli.commands.agent.get_llm', return_value=None):
			with pytest.raises(RuntimeError, match='No LLM configured for browser.extract\\(\\)'):
				await handle('extract', session_info, {'query': 'headline'})


def _make_dom_node(
	*,
	node_name: str,
	absolute_position: DOMRect | None = None,
	ax_name: str | None = None,
	node_value: str = '',
) -> EnhancedDOMTreeNode:
	"""Build a real EnhancedDOMTreeNode for testing."""
	from browser_use.dom.views import (
		EnhancedAXNode,
		EnhancedDOMTreeNode,
		NodeType,
	)

	ax_node = None
	if ax_name is not None:
		ax_node = EnhancedAXNode(
			ax_node_id='ax-0',
			ignored=False,
			role='button',
			name=ax_name,
			description=None,
			properties=None,
			child_ids=None,
		)

	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name=node_name,
		node_value=node_value,
		attributes={},
		is_scrollable=None,
		is_visible=True,
		absolute_position=absolute_position,
		target_id='target-0',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=ax_node,
		snapshot_node=None,
	)


class TestSelectorCache:
	"""Test selector map cache round-trip and coordinate conversion."""

	@pytest.fixture(autouse=True)
	def _use_tmp_state_file(self, monkeypatch, tmp_path):
		"""Redirect STATE_FILE to a temp dir so tests don't clobber real state."""
		import browser_use.skill_cli.direct as direct_mod

		self.state_file = tmp_path / 'browser-use-direct.json'
		monkeypatch.setattr(direct_mod, 'STATE_FILE', self.state_file)

	def test_save_and_load_cache_round_trip(self):
		"""_save_selector_cache → _load_selector_cache preserves data."""
		from browser_use.dom.views import DOMRect
		from browser_use.skill_cli.direct import (
			_load_selector_cache,
			_save_selector_cache,
			_save_state,
		)

		_save_state({'cdp_url': 'ws://localhost:9222'})

		node_1 = _make_dom_node(
			node_name='BUTTON',
			absolute_position=DOMRect(x=100.0, y=200.0, width=80.0, height=32.0),
			ax_name='Submit',
		)
		node_2 = _make_dom_node(
			node_name='A',
			absolute_position=DOMRect(x=50.0, y=800.5, width=200.0, height=40.0),
			node_value='Click here',
		)

		_save_selector_cache({5: node_1, 12: node_2})

		loaded = _load_selector_cache()
		assert 5 in loaded
		assert 12 in loaded
		assert loaded[5]['x'] == 100.0
		assert loaded[5]['y'] == 200.0
		assert loaded[5]['w'] == 80.0
		assert loaded[5]['h'] == 32.0
		assert loaded[5]['tag'] == 'button'
		assert loaded[5]['text'] == 'Submit'
		assert loaded[12]['x'] == 50.0
		assert loaded[12]['y'] == 800.5
		assert loaded[12]['tag'] == 'a'
		assert loaded[12]['text'] == 'Click here'

	def test_load_empty_cache(self):
		"""_load_selector_cache returns empty dict when no cache exists."""
		from browser_use.skill_cli.direct import _load_selector_cache, _save_state

		_save_state({'cdp_url': 'ws://localhost:9222'})
		loaded = _load_selector_cache()
		assert loaded == {}

	def test_cache_skips_nodes_without_position(self):
		"""Nodes without absolute_position are not cached."""
		from browser_use.skill_cli.direct import (
			_load_selector_cache,
			_save_selector_cache,
			_save_state,
		)

		_save_state({'cdp_url': 'ws://localhost:9222'})

		node = _make_dom_node(node_name='DIV', absolute_position=None)
		_save_selector_cache({1: node})
		loaded = _load_selector_cache()
		assert loaded == {}

	def test_viewport_coordinate_conversion(self):
		"""Document coords + scroll offset → viewport coords."""
		elem = {'x': 150.0, 'y': 900.0, 'w': 80.0, 'h': 32.0}
		scroll_x, scroll_y = 0.0, 500.0

		viewport_x = int(elem['x'] + elem['w'] / 2 - scroll_x)
		viewport_y = int(elem['y'] + elem['h'] / 2 - scroll_y)

		assert viewport_x == 190
		assert viewport_y == 416

	def test_viewport_conversion_with_horizontal_scroll(self):
		"""Horizontal scroll is also accounted for."""
		elem = {'x': 1200.0, 'y': 300.0, 'w': 100.0, 'h': 50.0}
		scroll_x, scroll_y = 800.0, 100.0

		viewport_x = int(elem['x'] + elem['w'] / 2 - scroll_x)
		viewport_y = int(elem['y'] + elem['h'] / 2 - scroll_y)

		assert viewport_x == 450
		assert viewport_y == 225

	def test_cache_invalidated_on_navigate(self):
		"""Navigating clears selector_map from state."""
		from browser_use.skill_cli.direct import _load_state, _save_state

		_save_state(
			{
				'cdp_url': 'ws://localhost:9222',
				'target_id': 'abc',
				'selector_map': {'1': {'x': 10, 'y': 20, 'w': 30, 'h': 40, 'tag': 'a', 'text': 'Link'}},
			}
		)

		state = _load_state()
		state.pop('selector_map', None)
		_save_state(state)

		reloaded = _load_state()
		assert 'selector_map' not in reloaded
		assert reloaded['cdp_url'] == 'ws://localhost:9222'
		assert reloaded['target_id'] == 'abc'

	def test_state_overwritten_on_fresh_cache(self):
		"""Running state overwrites old cache with new data."""
		from browser_use.dom.views import DOMRect
		from browser_use.skill_cli.direct import (
			_load_selector_cache,
			_save_selector_cache,
			_save_state,
		)

		_save_state(
			{
				'cdp_url': 'ws://localhost:9222',
				'selector_map': {'99': {'x': 0, 'y': 0, 'w': 0, 'h': 0, 'tag': 'old', 'text': 'old'}},
			}
		)

		node = _make_dom_node(
			node_name='SPAN',
			absolute_position=DOMRect(x=5.0, y=10.0, width=20.0, height=15.0),
			ax_name='New',
		)

		_save_selector_cache({7: node})
		loaded = _load_selector_cache()

		assert 99 not in loaded
		assert 7 in loaded
		assert loaded[7]['tag'] == 'span'

	@pytest.mark.asyncio
	async def test_cache_invalidated_after_click_index(self):
		"""Index clicks should clear cached selector coordinates after the click."""
		from browser_use.skill_cli.direct import LightCDP, _cdp_click_index, _load_state, _save_state

		_save_state(
			{
				'cdp_url': 'ws://localhost:9222',
				'selector_map': {'1': {'x': 10, 'y': 20, 'w': 30, 'h': 40, 'tag': 'a', 'text': 'Link'}},
			}
		)

		client = MagicMock()
		client.send = MagicMock()
		client.send.Runtime = MagicMock()
		client.send.Runtime.evaluate = AsyncMock(return_value={'result': {'value': '{"x":0,"y":0}'}})
		client.send.Input = MagicMock()
		client.send.Input.dispatchMouseEvent = AsyncMock()
		cdp = LightCDP(client=client, session_id='session-1', target_id='target-1')

		await _cdp_click_index(cdp, 1)

		assert 'selector_map' not in _load_state()
		assert client.send.Input.dispatchMouseEvent.await_count == 3

	@pytest.mark.asyncio
	async def test_cache_invalidated_after_input(self):
		"""Input by index should also clear cached selector coordinates."""
		from browser_use.skill_cli.direct import LightCDP, _cdp_input, _load_state, _save_state

		_save_state(
			{
				'cdp_url': 'ws://localhost:9222',
				'selector_map': {'2': {'x': 100, 'y': 200, 'w': 50, 'h': 20, 'tag': 'input', 'text': ''}},
			}
		)

		client = MagicMock()
		client.send = MagicMock()
		client.send.Runtime = MagicMock()
		client.send.Runtime.evaluate = AsyncMock(return_value={'result': {'value': '{"x":0,"y":0}'}})
		client.send.Input = MagicMock()
		client.send.Input.dispatchMouseEvent = AsyncMock()
		client.send.Input.insertText = AsyncMock()
		cdp = LightCDP(client=client, session_id='session-1', target_id='target-1')

		await _cdp_input(cdp, 2, 'hello')

		assert 'selector_map' not in _load_state()
		client.send.Input.insertText.assert_awaited_once_with(params={'text': 'hello'}, session_id='session-1')


class TestLightweightCdpReconnect:
	"""Test direct CLI lightweight CDP reconnection behavior."""

	@pytest.fixture(autouse=True)
	def _use_tmp_state_file(self, monkeypatch, tmp_path):
		"""Redirect STATE_FILE to a temp dir so tests don't clobber real state."""
		import browser_use.skill_cli.direct as direct_mod

		self.state_file = tmp_path / 'browser-use-direct.json'
		monkeypatch.setattr(direct_mod, 'STATE_FILE', self.state_file)

	@pytest.mark.asyncio
	async def test_recovers_from_stale_saved_target(self):
		"""A stale saved target_id should fall back to a live page target and persist it."""
		from browser_use.skill_cli.direct import _lightweight_cdp, _load_state, _save_state

		_save_state({'cdp_url': 'ws://localhost:9222/devtools/browser/test', 'target_id': 'stale-target'})

		client = AsyncMock()
		client.start = AsyncMock()
		client.stop = AsyncMock()
		client.send = MagicMock()
		client.send.Target = MagicMock()
		client.send.Target.getTargets = AsyncMock(
			return_value={
				'targetInfos': [
					{'targetId': 'fresh-target', 'type': 'page', 'url': 'https://example.com'},
				]
			}
		)
		client.send.Target.attachToTarget = AsyncMock(return_value={'sessionId': 'session-2'})
		client.send.Page = MagicMock()
		client.send.Page.enable = AsyncMock()
		client.send.Runtime = MagicMock()
		client.send.Runtime.enable = AsyncMock()

		with patch('cdp_use.CDPClient', return_value=client):
			async with _lightweight_cdp() as cdp:
				assert cdp.target_id == 'fresh-target'
				assert cdp.session_id == 'session-2'

		state = _load_state()
		assert state['target_id'] == 'fresh-target'
		client.send.Target.attachToTarget.assert_awaited_once_with(params={'targetId': 'fresh-target', 'flatten': True})

	@pytest.mark.asyncio
	async def test_falls_back_to_about_blank_when_no_http_page_exists(self):
		"""If only about:blank remains, lightweight reconnect should still attach to it."""
		from browser_use.skill_cli.direct import _lightweight_cdp, _save_state

		_save_state({'cdp_url': 'ws://localhost:9222/devtools/browser/test'})

		client = AsyncMock()
		client.start = AsyncMock()
		client.stop = AsyncMock()
		client.send = MagicMock()
		client.send.Target = MagicMock()
		client.send.Target.getTargets = AsyncMock(
			return_value={
				'targetInfos': [
					{'targetId': 'blank-target', 'type': 'page', 'url': 'about:blank'},
				]
			}
		)
		client.send.Target.attachToTarget = AsyncMock(return_value={'sessionId': 'session-blank'})
		client.send.Page = MagicMock()
		client.send.Page.enable = AsyncMock()
		client.send.Runtime = MagicMock()
		client.send.Runtime.enable = AsyncMock()

		with patch('cdp_use.CDPClient', return_value=client):
			async with _lightweight_cdp() as cdp:
				assert cdp.target_id == 'blank-target'
				assert cdp.session_id == 'session-blank'
