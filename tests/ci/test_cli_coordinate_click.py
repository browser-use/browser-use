"""Tests for CLI coordinate clicking support.

Verifies that the CLI correctly parses both index-based and coordinate-based
click commands, and that the browser command handler dispatches the right events.
"""

from __future__ import annotations

import pytest

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


class TestClickCommandHandler:
	"""Test the browser command handler dispatches correctly for click."""

	async def test_coordinate_click_handler(self, httpserver):
		"""Coordinate click dispatches ClickCoordinateEvent."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
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
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			result = await handle('click', session_info, {'args': [100, 200]})
			assert 'clicked_coordinate' in result
			assert result['clicked_coordinate'] == {'x': 100, 'y': 200}
		finally:
			await session.kill()

	async def test_index_click_handler(self, httpserver):
		"""Index click dispatches ClickElementEvent."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
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
				headed=False,
				profile=None,
				cdp_url=None,
				browser_session=session,
				actions=ActionHandler(session),
			)

			# Index 999 won't exist, so we expect the error path
			result = await handle('click', session_info, {'args': [999]})
			assert 'error' in result
		finally:
			await session.kill()

	async def test_invalid_args_count(self):
		"""Three args returns error without touching the browser."""
		from browser_use.browser.session import BrowserSession
		from browser_use.skill_cli.actions import ActionHandler
		from browser_use.skill_cli.commands.browser import handle
		from browser_use.skill_cli.sessions import SessionInfo

		# BrowserSession constructed but not started — handler hits the
		# 3-arg error branch before doing anything with the session.
		session_info = SessionInfo(
			name='test',
			headed=False,
			profile=None,
			cdp_url=None,
			browser_session=BrowserSession(headless=True),
			actions=ActionHandler(BrowserSession(headless=True)),
		)

		result = await handle('click', session_info, {'args': [1, 2, 3]})
		assert 'error' in result
		assert 'Usage' in result['error']
