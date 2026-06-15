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


def test_headed_flag_default_is_false():
	"""Test that --headed defaults to False when not specified."""
	parser = build_parser()

	args = parser.parse_args(['open', 'http://example.com'])
	assert args.headed is False, '--headed should default to False'


def test_headed_flag_with_profile():
	"""Test --headed works with --profile flag."""
	parser = build_parser()

	args = parser.parse_args(['--headed', '--profile', 'Default', 'open', 'http://example.com'])
	assert args.headed is True
	assert args.profile == 'Default'


def test_profile_bare_flag():
	"""Test bare --profile defaults to 'Default'.

	Note: bare --profile only works when followed by another flag (not a subcommand),
	because argparse nargs='?' greedily consumes the next non-flag token as the value.
	"""
	parser = build_parser()

	# Bare --profile before another flag: const='Default' is used
	args = parser.parse_args(['--profile', '--headed', 'open', 'http://example.com'])
	assert args.profile == 'Default'
	assert args.headed is True
	assert args.command == 'open'


def test_profile_with_name():
	"""Test --profile with an explicit name."""
	parser = build_parser()

	args = parser.parse_args(['--profile', 'Profile 1', 'open', 'http://example.com'])
	assert args.profile == 'Profile 1'


def test_no_profile_defaults_to_none():
	"""Test that profile defaults to None when not specified."""
	parser = build_parser()

	args = parser.parse_args(['open', 'http://example.com'])
	assert args.profile is None
