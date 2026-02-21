"""Tests for server locking to prevent race conditions."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import portalocker
import pytest

from browser_use.skill_cli.utils import (
	cleanup_session_files,
	get_lock_path,
	get_pid_path,
	is_server_running,
	is_session_locked,
	kill_orphaned_server,
	try_acquire_server_lock,
)


@pytest.fixture
def test_session():
	"""Provide a unique test session name and cleanup after."""
	session = f'test-lock-{os.getpid()}-{time.time_ns()}'
	yield session
	cleanup_session_files(session)


def test_lock_path_generation(test_session):
	"""Test that lock path is generated correctly."""
	path = get_lock_path(test_session)
	assert path.parent == Path(tempfile.gettempdir())
	assert path.name == f'browser-use-{test_session}.lock'


def test_try_acquire_server_lock_success(test_session):
	"""Test acquiring lock when no one holds it."""
	lock = try_acquire_server_lock(test_session)
	assert lock is not None

	# Should block second acquisition
	lock2 = try_acquire_server_lock(test_session)
	assert lock2 is None

	# Release first lock
	portalocker.unlock(lock)
	lock.close()

	# Now should succeed
	lock3 = try_acquire_server_lock(test_session)
	assert lock3 is not None
	portalocker.unlock(lock3)
	lock3.close()


def test_is_session_locked(test_session):
	"""Test detecting if session is locked."""
	# Initially not locked
	assert is_session_locked(test_session) is False

	# Acquire lock
	lock = try_acquire_server_lock(test_session)
	assert lock is not None

	# Now should be locked
	assert is_session_locked(test_session) is True

	# Release
	portalocker.unlock(lock)
	lock.close()

	# No longer locked
	assert is_session_locked(test_session) is False


def test_kill_orphaned_server_no_pid_file(test_session):
	"""Test that kill_orphaned_server returns False when no PID file."""
	assert kill_orphaned_server(test_session) is False


def test_kill_orphaned_server_with_lock(test_session):
	"""Test that kill_orphaned_server doesn't kill server holding lock."""
	# Create PID file pointing to current process
	pid_path = get_pid_path(test_session)
	pid_path.write_text(str(os.getpid()))

	# Acquire lock (simulating a healthy server)
	lock = try_acquire_server_lock(test_session)
	assert lock is not None

	# Should not kill - server is healthy (has lock)
	assert kill_orphaned_server(test_session) is False

	portalocker.unlock(lock)
	lock.close()


def test_cleanup_includes_lock_file(test_session):
	"""Test that cleanup removes lock file."""
	lock_path = get_lock_path(test_session)
	pid_path = get_pid_path(test_session)

	# Create files
	lock_path.touch()
	pid_path.write_text('12345')

	assert lock_path.exists()
	assert pid_path.exists()

	cleanup_session_files(test_session)

	assert not lock_path.exists()
	assert not pid_path.exists()


def test_concurrent_lock_acquisition(test_session):
	"""Test that only one process can hold the lock."""
	lock_path = get_lock_path(test_session)
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	lock_path.touch()

	# Acquire lock in current process
	lock = try_acquire_server_lock(test_session)
	assert lock is not None

	# Try to acquire in subprocess - should fail
	result = subprocess.run(
		[
			sys.executable,
			'-c',
			f'''
import portalocker
from pathlib import Path

lock_path = Path("{lock_path}")
f = open(lock_path, 'r+')
try:
    portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
    print("ACQUIRED")
except portalocker.LockException:
    print("BLOCKED")
f.close()
''',
		],
		capture_output=True,
		text=True,
		timeout=5,
	)

	assert 'BLOCKED' in result.stdout

	# Release lock
	portalocker.unlock(lock)
	lock.close()

	# Now subprocess should succeed
	result = subprocess.run(
		[
			sys.executable,
			'-c',
			f'''
import portalocker
from pathlib import Path

lock_path = Path("{lock_path}")
f = open(lock_path, 'r+')
try:
    portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
    print("ACQUIRED")
    portalocker.unlock(f)
except portalocker.LockException:
    print("BLOCKED")
f.close()
''',
		],
		capture_output=True,
		text=True,
		timeout=5,
	)

	assert 'ACQUIRED' in result.stdout


def test_lock_released_on_process_death(test_session):
	"""Test that lock is automatically released when process dies."""
	lock_path = get_lock_path(test_session)
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	lock_path.touch()

	# Start subprocess that holds lock
	proc = subprocess.Popen(
		[
			sys.executable,
			'-c',
			f'''
import portalocker
import time
from pathlib import Path

lock_path = Path("{lock_path}")
f = open(lock_path, 'r+')
portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
print("LOCKED", flush=True)
time.sleep(60)  # Hold lock
''',
		],
		stdout=subprocess.PIPE,
		text=True,
	)

	# Wait for lock acquisition
	assert proc.stdout is not None
	line = proc.stdout.readline()
	assert 'LOCKED' in line

	# Verify we can't acquire
	lock = try_acquire_server_lock(test_session)
	assert lock is None

	# Kill the process
	proc.terminate()
	proc.wait(timeout=5)

	# Small delay for OS to release lock
	time.sleep(0.1)

	# Now we should be able to acquire
	lock = try_acquire_server_lock(test_session)
	assert lock is not None
	portalocker.unlock(lock)
	lock.close()


def test_is_server_running_without_pid(test_session):
	"""Test is_server_running returns False when no PID file."""
	assert is_server_running(test_session) is False


def test_is_server_running_with_current_pid(test_session):
	"""Test is_server_running returns True when PID file points to live process."""
	pid_path = get_pid_path(test_session)
	pid_path.write_text(str(os.getpid()))

	assert is_server_running(test_session) is True


def test_is_server_running_with_dead_pid(test_session):
	"""Test is_server_running returns False when PID file points to dead process."""
	pid_path = get_pid_path(test_session)
	# Use a PID that's very unlikely to exist
	pid_path.write_text('999999999')

	assert is_server_running(test_session) is False
