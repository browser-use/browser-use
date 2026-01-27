"""Tests for CLI argument parsing, specifically the --headed flag behavior."""

from browser_use.skill_cli.main import build_parser


def test_headed_flag_before_open_subcommand():
	"""Test that --headed flag before 'open' subcommand is properly parsed.

	Regression test for issue #3931: The open subparser had a duplicate --headed
	argument that shadowed the global --headed flag, causing the global flag
	to be overwritten with False when parsing 'browser-use --headed open <url>'.
	"""
	parser = build_parser()

	# This was the failing case: --headed before 'open' was being ignored
	args = parser.parse_args(['--headed', 'open', 'http://example.com'])
	assert args.headed is True, 'Global --headed flag should be True when specified before subcommand'
	assert args.url == 'http://example.com'
	assert args.command == 'open'


def test_headed_flag_with_session():
	"""Test that --headed works with other global flags like -s/--session."""
	parser = build_parser()

	args = parser.parse_args(['--headed', '-s', 'mysession', 'open', 'http://example.com'])
	assert args.headed is True
	assert args.session == 'mysession'
	assert args.url == 'http://example.com'


def test_headed_flag_default_is_false():
	"""Test that --headed defaults to False when not specified."""
	parser = build_parser()

	args = parser.parse_args(['open', 'http://example.com'])
	assert args.headed is False, '--headed should default to False'


def test_headed_flag_with_browser_mode():
	"""Test --headed works with --browser flag."""
	parser = build_parser()

	args = parser.parse_args(['--headed', '--browser', 'chromium', 'open', 'http://example.com'])
	assert args.headed is True
	assert args.browser == 'chromium'
