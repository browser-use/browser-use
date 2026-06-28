"""Tests for CLI tab management commands."""

from __future__ import annotations

import pytest

from browser_use.skill_cli.main import build_parser


class TestTabArgParsing:
	"""Test argparse handles the tab command group."""

	def test_tab_list(self):
		"""browser-use tab list -> correct args."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'list'])
		assert args.command == 'tab'
		assert args.tab_command == 'list'

	def test_tab_new_default_url(self):
		"""browser-use tab new -> about:blank."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'new'])
		assert args.command == 'tab'
		assert args.tab_command == 'new'
		assert args.url == 'about:blank'

	def test_tab_new_with_url(self):
		"""browser-use tab new <url> preserves the URL."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'new', 'https://example.com'])
		assert args.tab_command == 'new'
		assert args.url == 'https://example.com'

	def test_tab_switch(self):
		"""browser-use tab switch <index> -> integer tab index."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'switch', '2'])
		assert args.command == 'tab'
		assert args.tab_command == 'switch'
		assert args.tab == 2

	def test_tab_close_without_indices(self):
		"""browser-use tab close -> close the current tab."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'close'])
		assert args.command == 'tab'
		assert args.tab_command == 'close'
		assert args.tabs == []

	def test_tab_close_with_indices(self):
		"""browser-use tab close <index...> -> integer tab indices."""
		parser = build_parser()
		args = parser.parse_args(['tab', 'close', '1', '3'])
		assert args.tab_command == 'close'
		assert args.tabs == [1, 3]

	def test_tab_unknown_subcommand_fails(self):
		"""Unknown tab subcommands fail during parsing."""
		parser = build_parser()
		with pytest.raises(SystemExit):
			parser.parse_args(['tab', 'missing'])
