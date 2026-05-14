"""Tests for splitting 'open --new-tab' into separate 'new-tab' and 'open' commands."""

from browser_use.skill_cli.main import build_parser


def test_new_tab_command_exists():
	"""new-tab is a standalone subcommand with no required arguments."""
	parser = build_parser()
	args = parser.parse_args(['new-tab'])
	assert args.command == 'new-tab'


def test_open_command_has_no_new_tab_flag():
	"""open no longer accepts --new-tab / -n flags."""
	parser = build_parser()
	# should parse without error and have no new_tab attribute
	args = parser.parse_args(['open', 'http://example.com'])
	assert not hasattr(args, 'new_tab')


def test_open_command_still_works():
	"""open <url> continues to work as before."""
	parser = build_parser()
	args = parser.parse_args(['open', 'http://example.com'])
	assert args.command == 'open'
	assert args.url == 'http://example.com'


def test_new_tab_with_global_flags():
	"""new-tab works alongside global flags like --headed and --session."""
	parser = build_parser()
	args = parser.parse_args(['--headed', '-s', 'mysession', 'new-tab'])
	assert args.command == 'new-tab'
	assert args.headed is True
	assert args.session == 'mysession'
