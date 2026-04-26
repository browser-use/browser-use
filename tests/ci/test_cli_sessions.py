"""Tests for multi-session daemon architecture.

Validates argument parsing, socket/PID path generation, session name validation,
and path agreement between main.py (stdlib-only) and utils.py.
"""

import argparse
import sys

import pytest

from browser_use.skill_cli.main import (
	_get_home_dir,
	_get_pid_path,
	_get_socket_path,
	_handle_sessions,
	_SessionProbe,
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


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows TCP session paths only')
def test_windows_socket_path_is_namespaced_by_home(tmp_path, monkeypatch):
	"""Different BROWSER_USE_HOME values should not reuse the same TCP port."""
	home_a = str(tmp_path / 'home-a')
	home_b = str(tmp_path / 'home-b')

	monkeypatch.setenv('BROWSER_USE_HOME', home_a)
	path_a = _get_socket_path('default')

	monkeypatch.setenv('BROWSER_USE_HOME', home_b)
	path_b = _get_socket_path('default')

	assert path_a != path_b
	assert path_b == get_socket_path('default')


def test_handle_sessions_reuses_probe_ping_data(tmp_path, monkeypatch, capsys):
	"""Sessions output should reuse cached probe data instead of pinging again."""
	home_dir = tmp_path / 'browser-use-home'
	home_dir.mkdir()
	(home_dir / 'demo.pid').write_text('12345')

	monkeypatch.setenv('BROWSER_USE_HOME', str(home_dir))

	def _fake_probe(session: str) -> _SessionProbe:
		return _SessionProbe(
			name=session,
			phase='ready',
			pid=12345,
			pid_alive=True,
			socket_reachable=True,
			socket_pid=12345,
			ping_data={
				'pid': 12345,
				'headed': False,
				'profile': 'demo-profile',
				'cdp_url': 'http://127.0.0.1:9222',
				'use_cloud': False,
			},
		)

	monkeypatch.setattr('browser_use.skill_cli.main._probe_session', _fake_probe)
	monkeypatch.setattr('browser_use.skill_cli.main.send_command', lambda *args, **kwargs: pytest.fail('unexpected extra ping'))

	result = _handle_sessions(argparse.Namespace(json=False))
	output = capsys.readouterr().out

	assert result == 0
	assert 'demo' in output
	assert 'profile=demo-profile' in output
	assert 'cdp' in output
