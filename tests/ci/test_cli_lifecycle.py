"""Tests for daemon lifecycle state file, session probing, and shutdown behavior.

Uses real daemon subprocesses with BROWSER_USE_HOME overridden to home_dir.
Daemons bind sockets and write state/PID files without launching browsers
(lazy session creation means the daemon is ready after socket bind).
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


@pytest.fixture
def home_dir():
	"""Short temp dir for daemon home (Unix socket paths are limited to ~104 chars)."""
	with tempfile.TemporaryDirectory(prefix='bu-') as d:
		yield Path(d)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _start_daemon(home_dir: Path, session: str = 'default', timeout: float = 10.0) -> int:
	"""Start a daemon subprocess. Returns the PID once the state file shows 'ready'."""
	home_dir.mkdir(parents=True, exist_ok=True)
	env = os.environ.copy()
	env['BROWSER_USE_HOME'] = str(home_dir)

	log_path = home_dir / f'{session}.test.log'
	log_file = open(log_path, 'w')
	proc = subprocess.Popen(
		[sys.executable, '-m', 'browser_use.skill_cli.daemon', '--session', session],
		env=env,
		stdout=log_file,
		stderr=log_file,
	)

	# Wait for the state file to show 'ready'
	state_path = home_dir / f'{session}.state.json'
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if state_path.exists():
			try:
				state = json.loads(state_path.read_text())
				if state.get('phase') in ('ready', 'running'):
					log_file.close()
					return proc.pid
			except (json.JSONDecodeError, OSError):
				pass
		time.sleep(0.1)

	proc.kill()
	proc.wait()
	log_file.close()
	log_content = log_path.read_text() if log_path.exists() else '(no log)'
	pytest.fail(f'Daemon did not reach ready state within {timeout}s\nLog:\n{log_content}')


def _read_state(home_dir: Path, session: str = 'default') -> dict | None:
	state_path = home_dir / f'{session}.state.json'
	if not state_path.exists():
		return None
	try:
		return json.loads(state_path.read_text())
	except (json.JSONDecodeError, OSError):
		return None


def _is_pid_alive(pid: int) -> bool:
	try:
		os.kill(pid, 0)
		return True
	except (OSError, ProcessLookupError):
		return False


def _kill_daemon(pid: int) -> None:
	try:
		os.kill(pid, signal.SIGTERM)
		for _ in range(50):
			time.sleep(0.1)
			if not _is_pid_alive(pid):
				return
		os.kill(pid, signal.SIGKILL)
	except (OSError, ProcessLookupError):
		pass


def _run_cli(*args: str, home_dir: Path) -> subprocess.CompletedProcess:
	env = os.environ.copy()
	env['BROWSER_USE_HOME'] = str(home_dir)
	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=30,
	)


# ---------------------------------------------------------------------------
# State file transitions
# ---------------------------------------------------------------------------


def test_daemon_writes_ready_state(home_dir):
	"""Daemon should write 'ready' state after binding socket."""
	pid = _start_daemon(home_dir)
	try:
		state = _read_state(home_dir)
		assert state is not None
		assert state['phase'] == 'ready'
		assert state['pid'] == pid
		assert 'updated_at' in state
		assert 'config' in state
	finally:
		_kill_daemon(pid)


def test_daemon_writes_stopped_on_shutdown(home_dir):
	"""Daemon should write 'stopped' state before exiting."""
	pid = _start_daemon(home_dir)
	os.kill(pid, signal.SIGTERM)

	# Wait for exit
	for _ in range(50):
		time.sleep(0.1)
		if not _is_pid_alive(pid):
			break

	state = _read_state(home_dir)
	assert state is not None
	assert state['phase'] == 'stopped'


def test_daemon_pid_file_and_state_agree(home_dir):
	"""PID in state file should match PID file content."""
	pid = _start_daemon(home_dir)
	try:
		state = _read_state(home_dir)
		assert state is not None
		pid_file = home_dir / 'default.pid'
		assert pid_file.exists()
		assert int(pid_file.read_text().strip()) == state['pid']
		assert state['pid'] == pid
	finally:
		_kill_daemon(pid)


# ---------------------------------------------------------------------------
# _probe_session branches
# ---------------------------------------------------------------------------


def test_probe_session_running_daemon(home_dir):
	"""Probe should see pid_alive=True, socket_reachable=True for a live daemon."""
	from browser_use.skill_cli.main import _probe_session

	pid = _start_daemon(home_dir)
	try:
		# Override home dir for probe
		old_env = os.environ.get('BROWSER_USE_HOME')
		os.environ['BROWSER_USE_HOME'] = str(home_dir)
		try:
			probe = _probe_session('default')
			assert probe.pid_alive
			assert probe.socket_reachable
			assert probe.pid == pid
			assert probe.phase == 'ready'
		finally:
			if old_env is None:
				os.environ.pop('BROWSER_USE_HOME', None)
			else:
				os.environ['BROWSER_USE_HOME'] = old_env
	finally:
		_kill_daemon(pid)


def test_probe_session_dead_pid(home_dir):
	"""Probe should see pid_alive=False for stale files with dead PID."""
	from browser_use.skill_cli.main import _probe_session

	# Write stale state + PID files
	(home_dir / 'ghost.state.json').write_text(
		json.dumps(
			{
				'phase': 'running',
				'pid': 99999999,
				'updated_at': time.time(),
				'config': {'headed': False, 'profile': None, 'cdp_url': None, 'use_cloud': False},
			}
		)
	)
	(home_dir / 'ghost.pid').write_text('99999999')

	old_env = os.environ.get('BROWSER_USE_HOME')
	os.environ['BROWSER_USE_HOME'] = str(home_dir)
	try:
		probe = _probe_session('ghost')
		assert not probe.pid_alive
		assert not probe.socket_reachable
		assert probe.phase == 'running'
		assert probe.pid == 99999999
	finally:
		if old_env is None:
			os.environ.pop('BROWSER_USE_HOME', None)
		else:
			os.environ['BROWSER_USE_HOME'] = old_env


def test_probe_session_no_files(home_dir):
	"""Probe should return empty for a session with no files."""
	from browser_use.skill_cli.main import _probe_session

	old_env = os.environ.get('BROWSER_USE_HOME')
	os.environ['BROWSER_USE_HOME'] = str(home_dir)
	try:
		probe = _probe_session('nonexistent')
		assert probe.pid is None
		assert not probe.pid_alive
		assert not probe.socket_reachable
		assert probe.phase is None
	finally:
		if old_env is None:
			os.environ.pop('BROWSER_USE_HOME', None)
		else:
			os.environ['BROWSER_USE_HOME'] = old_env


def test_probe_session_corrupt_state_file(home_dir):
	"""Probe should handle corrupt state file gracefully."""
	from browser_use.skill_cli.main import _probe_session

	(home_dir / 'corrupt.state.json').write_text('not json{{{')

	old_env = os.environ.get('BROWSER_USE_HOME')
	os.environ['BROWSER_USE_HOME'] = str(home_dir)
	try:
		probe = _probe_session('corrupt')
		assert probe.phase is None  # corrupt file treated as missing
		assert not probe.pid_alive
	finally:
		if old_env is None:
			os.environ.pop('BROWSER_USE_HOME', None)
		else:
			os.environ['BROWSER_USE_HOME'] = old_env


# ---------------------------------------------------------------------------
# Close behavior
# ---------------------------------------------------------------------------


def test_close_via_socket(home_dir):
	"""Normal close should send shutdown command and report success."""
	pid = _start_daemon(home_dir)
	result = _run_cli('close', home_dir=home_dir)

	assert result.returncode == 0, f'close failed: stdout={result.stdout!r} stderr={result.stderr!r}'
	assert 'Browser closed' in result.stdout

	# Clean up daemon if it's still shutting down
	_kill_daemon(pid)


def test_close_orphaned_daemon(home_dir):
	"""Close should handle an orphaned daemon (socket deleted but PID alive)."""
	pid = _start_daemon(home_dir)

	# Delete socket to simulate orphan
	for sock in home_dir.glob('*.sock'):
		sock.unlink()

	result = _run_cli('close', home_dir=home_dir)
	assert result.returncode == 0, f'close failed: stdout={result.stdout!r} stderr={result.stderr!r}'
	# Race between socket deletion and CLI probe means several outcomes are valid:
	# - "Browser closed" (killed orphan successfully)
	# - "No active browser session" (daemon already exited)
	# - "daemon may still be shutting down" on stderr (SIGTERM sent but PID hasn't died yet)
	assert 'Browser closed' in result.stdout or 'No active browser session' in result.stdout or 'shutting down' in result.stderr

	# Clean up — daemon may still be shutting down asynchronously
	_kill_daemon(pid)


def test_close_no_session(home_dir):
	"""Close with no active session should report nothing."""
	result = _run_cli('close', home_dir=home_dir)
	assert result.returncode == 0
	assert 'No active browser session' in result.stdout


# ---------------------------------------------------------------------------
# Close --all behavior
# ---------------------------------------------------------------------------


def test_close_all_multiple_sessions(home_dir):
	"""Close --all should report closing all sessions including orphans."""
	pid1 = _start_daemon(home_dir, session='s1')
	pid2 = _start_daemon(home_dir, session='s2')

	# Orphan s2 by deleting its socket
	for sock in home_dir.glob('s2.sock'):
		sock.unlink()

	result = _run_cli('close', '--all', home_dir=home_dir)
	assert result.returncode == 0
	# s1 closed via socket, s2 may have been killed or already dead (race)
	assert 'Closed' in result.stdout and 'session(s)' in result.stdout

	# Clean up any stragglers
	_kill_daemon(pid1)
	_kill_daemon(pid2)


def test_close_all_no_sessions(home_dir):
	"""Close --all with nothing running."""
	result = _run_cli('close', '--all', home_dir=home_dir)
	assert result.returncode == 0
	assert 'No active sessions' in result.stdout


# ---------------------------------------------------------------------------
# Sessions command
# ---------------------------------------------------------------------------


def test_sessions_lists_daemon(home_dir):
	"""Sessions should list a running daemon with its phase."""
	pid = _start_daemon(home_dir)
	try:
		result = _run_cli('sessions', home_dir=home_dir)
		assert result.returncode == 0
		assert 'default' in result.stdout
		assert 'ready' in result.stdout
	finally:
		_kill_daemon(pid)


def test_sessions_cleans_dead(home_dir):
	"""Sessions should clean up stale files for dead daemons."""
	# Write stale files
	(home_dir / 'dead.state.json').write_text(
		json.dumps(
			{
				'phase': 'running',
				'pid': 99999999,
				'updated_at': time.time(),
				'config': {'headed': False, 'profile': None, 'cdp_url': None, 'use_cloud': False},
			}
		)
	)
	(home_dir / 'dead.pid').write_text('99999999')

	result = _run_cli('sessions', home_dir=home_dir)
	assert result.returncode == 0

	# Stale files should be cleaned
	assert not (home_dir / 'dead.state.json').exists()
	assert not (home_dir / 'dead.pid').exists()


def test_sessions_cleans_terminal_state(home_dir):
	"""Sessions should clean up stopped/failed state files."""
	(home_dir / 'old.state.json').write_text(
		json.dumps(
			{
				'phase': 'stopped',
				'pid': 99999999,
				'updated_at': time.time(),
				'config': {'headed': False, 'profile': None, 'cdp_url': None, 'use_cloud': False},
			}
		)
	)

	result = _run_cli('sessions', home_dir=home_dir)
	assert result.returncode == 0
	assert not (home_dir / 'old.state.json').exists()
