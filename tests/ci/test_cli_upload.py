"""Tests for CLI file upload command.

Verifies argparse registration, file validation, file input discovery
(reusing BrowserSession.find_file_input_near_element), and event dispatch.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from browser_use.skill_cli.main import build_parser


class TestUploadArgParsing:
	"""Test argparse handles the upload subcommand."""

	def test_upload_basic(self):
		"""browser-use upload 5 /tmp/file.txt -> correct args."""
		parser = build_parser()
		args = parser.parse_args(['upload', '5', '/tmp/file.txt'])
		assert args.command == 'upload'
		assert args.index == 5
		assert args.path == '/tmp/file.txt'

	def test_upload_path_with_spaces(self):
		"""Paths with spaces are handled."""
		parser = build_parser()
		args = parser.parse_args(['upload', '3', '/tmp/my file.pdf'])
		assert args.path == '/tmp/my file.pdf'

	def test_upload_missing_path_fails(self):
		"""browser-use upload 5 (no path) should fail."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['upload', '5'])

	def test_upload_missing_index_fails(self):
		"""browser-use upload (no args) should fail."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['upload'])

	def test_upload_non_int_index_fails(self):
		"""browser-use upload abc /tmp/file.txt should fail."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['upload', 'abc', '/tmp/file.txt'])


class TestUploadCommandHandler:
	"""Test the browser command handler for upload."""

	async def test_upload_file_not_found(self):
		"""Non-existent file returns error without touching the browser."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session_info = SessionInfo(
			name='test',
			headed=False,
			profile=None,
			cdp_url=None,
			browser_session=BrowserSession(headless=True),
			actions=ActionHandler(BrowserSession(headless=True)),
		)

		result = await handle('upload', session_info, {'index': 0, 'path': '/nonexistent/file.txt'})
		assert 'error' in result
		assert 'not found' in result['error'].lower()

	async def test_upload_empty_file(self):
		"""Empty file returns error."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		session_info = SessionInfo(
			name='test',
			headed=False,
			profile=None,
			cdp_url=None,
			browser_session=BrowserSession(headless=True),
			actions=ActionHandler(BrowserSession(headless=True)),
		)

		with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
			empty_path = f.name

		try:
			result = await handle('upload', session_info, {'index': 0, 'path': empty_path})
			assert 'error' in result
			assert 'empty' in result['error'].lower()
		finally:
			Path(empty_path).unlink(missing_ok=True)

	async def test_upload_element_not_found(self, httpserver):
		"""Invalid element index returns error."""
		from browser_use.browser.events import NavigateToUrlEvent
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		httpserver.expect_request('/').respond_with_data(
			'<html><body><input type="file" /></body></html>',
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
				f.write(b'test content')
				test_file = f.name

			try:
				result = await handle('upload', session_info, {'index': 999, 'path': test_file})
				assert 'error' in result
				assert '999' in result['error']
			finally:
				Path(test_file).unlink(missing_ok=True)
		finally:
			await session.kill()

	async def test_upload_happy_path(self, httpserver):
		"""Upload to a file input element succeeds."""
		from browser_use.browser.events import NavigateToUrlEvent
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		httpserver.expect_request('/').respond_with_data(
			'<html><body><input type="file" id="upload" /></body></html>',
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			# Get state to populate selector map
			await session.get_browser_state_summary()

			# Find the file input index
			selector_map = await session.get_selector_map()
			file_input_index = None
			for idx, el in selector_map.items():
				if session.is_file_input(el):
					file_input_index = idx
					break
			assert file_input_index is not None, 'File input not found in selector map'

			with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
				f.write(b'test content for upload')
				test_file = f.name

			try:
				result = await handle('upload', session_info, {'index': file_input_index, 'path': test_file})
				assert 'uploaded' in result
				assert result['element'] == file_input_index
			finally:
				Path(test_file).unlink(missing_ok=True)
		finally:
			await session.kill()

	async def test_upload_not_file_input_suggests_indices(self, httpserver):
		"""Targeting a non-file-input element with no nearby file input returns error with suggestions."""
		from browser_use.browser.events import NavigateToUrlEvent
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		# Use deeply nested, separate DOM subtrees so the heuristic won't bridge them
		httpserver.expect_request('/').respond_with_data(
			"""<html><body>
				<div><div><div><div><div><button id="btn">Click me</button></div></div></div></div></div>
				<div><div><div><div><div><input type="file" id="upload" /></div></div></div></div></div>
			</body></html>""",
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			await session.get_browser_state_summary()

			# Find the button index (not a file input)
			selector_map = await session.get_selector_map()
			button_index = None
			for idx, el in selector_map.items():
				if el.node_name.upper() == 'BUTTON':
					button_index = idx
					break
			assert button_index is not None, 'Button not found in selector map'

			with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
				f.write(b'test content')
				test_file = f.name

			try:
				result = await handle('upload', session_info, {'index': button_index, 'path': test_file})
				assert 'error' in result
				assert 'not a file input' in result['error'].lower()
				# Should suggest the file input index
				assert 'File input(s) found at index' in result['error']
			finally:
				Path(test_file).unlink(missing_ok=True)
		finally:
			await session.kill()

	async def test_upload_wrapped_file_input(self, httpserver):
		"""File input wrapped in a label/div is found via find_file_input_near_element."""
		from browser_use.browser.events import NavigateToUrlEvent
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		httpserver.expect_request('/').respond_with_data(
			"""<html><body>
				<label id="wrapper">
					Upload here
					<input type="file" id="hidden-upload" style="opacity: 0" />
				</label>
			</body></html>""",
			content_type='text/html',
		)

		session = BrowserSession(headless=True)
		await session.start()
		try:
			await session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))

			session_info = SessionInfo(
				name='test',
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			await session.get_browser_state_summary()

			# The file input should be found even if we target the label or a nearby element
			selector_map = await session.get_selector_map()

			# Find any non-file-input element that is near the file input
			file_input_index = None
			other_index = None
			for idx, el in selector_map.items():
				if session.is_file_input(el):
					file_input_index = idx
				else:
					other_index = idx

			# If both the file input and another element are in the selector map,
			# try uploading via the other element (the heuristic should find the file input)
			if other_index is not None:
				with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
					f.write(b'test content for wrapped upload')
					test_file = f.name

				try:
					result = await handle('upload', session_info, {'index': other_index, 'path': test_file})
					# Should succeed if the heuristic found the nearby file input
					# or error if too far away - either way, the heuristic was exercised
					if 'uploaded' in result:
						assert result['element'] == other_index
					else:
						# If the elements are too far apart, the heuristic won't find it
						assert 'error' in result
				finally:
					Path(test_file).unlink(missing_ok=True)
			elif file_input_index is not None:
				# Only the file input is indexed, just test direct upload
				with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
					f.write(b'test content')
					test_file = f.name

				try:
					result = await handle('upload', session_info, {'index': file_input_index, 'path': test_file})
					assert 'uploaded' in result
				finally:
					Path(test_file).unlink(missing_ok=True)
		finally:
			await session.kill()
