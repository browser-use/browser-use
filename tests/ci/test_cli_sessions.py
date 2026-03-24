"""Tests for multi-session daemon architecture.

Validates argument parsing, socket/PID path generation, session name validation,
and path agreement between main.py (stdlib-only) and utils.py.
"""

import pytest

from browser_use.skill_cli.main import (
	_get_home_dir,
	_get_pid_path,
	_get_socket_path,
	build_parser,
)
from browser_use.skill_cli.utils import (
	get_home_dir,
	get_pid_path,
	get_socket_path,
	validate_session_name,
)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_session_flag_parsing():
	parser = build_parser()
	args = parser.parse_args(['--session', 'work', 'state'])
	assert args.session == 'work'
	assert args.command == 'state'


def test_session_default_is_none():
	parser = build_parser()
	args = parser.parse_args(['state'])
	assert args.session is None


def test_sessions_command_parsing():
	parser = build_parser()
	args = parser.parse_args(['sessions'])
	assert args.command == 'sessions'


def test_close_all_flag():
	parser = build_parser()
	args = parser.parse_args(['close', '--all'])
	assert args.command == 'close'
	assert args.all is True


def test_close_without_all():
	parser = build_parser()
	args = parser.parse_args(['close'])
	assert args.command == 'close'
	assert args.all is False


# ---------------------------------------------------------------------------
# Session name validation
# ---------------------------------------------------------------------------


def test_session_name_valid():
	for name in ['default', 'work', 'my-session_1', 'A', '123']:
		validate_session_name(name)  # Should not raise


def test_session_name_invalid():
	for name in ['../evil', 'has space', 'semi;colon', 'slash/bad', '', 'a.b']:
		with pytest.raises(ValueError):
			validate_session_name(name)


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def test_socket_path_includes_session():
	path = _get_socket_path('work')
	assert 'work.sock' in path or 'tcp://' in path


def test_pid_path_includes_session():
	path = _get_pid_path('work')
	assert path.name == 'work.pid'


def test_default_session_paths():
	sock = _get_socket_path('default')
	pid = _get_pid_path('default')
	assert 'default.sock' in sock or 'tcp://' in sock
	assert pid.name == 'default.pid'


# ---------------------------------------------------------------------------
# Path agreement between main.py and utils.py
# ---------------------------------------------------------------------------


def test_main_utils_socket_path_agreement():
	"""main._get_socket_path must produce identical results to utils.get_socket_path."""
	for session in ['default', 'work', 'my-session_1', 'a', 'UPPER']:
		assert _get_socket_path(session) == get_socket_path(session), f'Socket mismatch for {session!r}'


def test_main_utils_pid_path_agreement():
	"""main._get_pid_path must produce identical results to utils.get_pid_path."""
	for session in ['default', 'work', 'my-session_1', 'a', 'UPPER']:
		assert _get_pid_path(session) == get_pid_path(session), f'PID mismatch for {session!r}'


def test_main_utils_home_dir_agreement():
	"""main._get_home_dir must produce identical results to utils.get_home_dir."""
	assert _get_home_dir() == get_home_dir()


def test_path_agreement_with_env_override(tmp_path, monkeypatch):
	"""Path agreement under BROWSER_USE_HOME override."""
	override = str(tmp_path / 'custom-home')
	monkeypatch.setenv('BROWSER_USE_HOME', override)

	assert _get_home_dir() == get_home_dir()
	assert _get_socket_path('test') == get_socket_path('test')
	assert _get_pid_path('test') == get_pid_path('test')
