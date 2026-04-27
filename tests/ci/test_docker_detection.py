"""Tests for is_running_in_docker() container detection logic."""

import os
from pathlib import Path
from unittest.mock import patch

from browser_use.config import is_running_in_docker


def _detect_fresh(**overrides) -> bool:
	"""Run is_running_in_docker with a clean cache.

	Patches out all OS-level checks by default so each test controls exactly
	which signals are present. Pass keyword arguments to override individual
	checks (e.g. ``dockerenv_exists=True``).

	Pass ``pid1_cmdline`` to simulate a PID 1 process with a specific command
	(e.g. ``['/usr/bin/python3', 'app.py']``). When omitted, ``psutil.Process``
	raises ``PermissionError`` so no PID 1 info is available.
	"""
	dockerenv = overrides.get('dockerenv_exists', False)
	containerenv = overrides.get('containerenv_exists', False)
	cgroup_text = overrides.get('cgroup_text', '')
	env_vars = overrides.get('env_vars', {})
	pid_count = overrides.get('pid_count', 100)
	pid1_cmdline: list[str] | None = overrides.get('pid1_cmdline', None)

	def fake_path_exists(self: Path) -> bool:
		s = str(self)
		if s == '/.dockerenv':
			return dockerenv
		if s == '/run/.containerenv':
			return containerenv
		return original_exists(self)

	original_exists = Path.exists

	# Build the psutil.Process mock: either return a fake with cmdline()
	# or raise PermissionError (simulating restricted access to PID 1).
	if pid1_cmdline is not None:
		fake_proc = type('FakeProcess', (), {'cmdline': lambda self: pid1_cmdline})()
		process_side_effect = None
		process_return_value = fake_proc
	else:
		process_side_effect = PermissionError
		process_return_value = None

	# Clear the @cache so each call re-evaluates
	is_running_in_docker.cache_clear()

	with (
		patch.object(Path, 'exists', fake_path_exists),
		patch.object(Path, 'read_text', return_value=cgroup_text),
		patch('psutil.pids', return_value=list(range(pid_count))),
		patch('psutil.Process', side_effect=process_side_effect, return_value=process_return_value),
		patch.dict(os.environ, env_vars, clear=False),
	):
		# Remove container-related env vars that might leak from the host
		for key in ('container', 'KUBERNETES_SERVICE_HOST'):
			if key not in env_vars:
				os.environ.pop(key, None)
		return is_running_in_docker()


# ---------------------------------------------------------------------------
# Positive signals — each should independently return True
# ---------------------------------------------------------------------------


def test_detects_dockerenv_file():
	assert _detect_fresh(dockerenv_exists=True) is True


def test_detects_docker_in_cgroup():
	assert _detect_fresh(cgroup_text='12:devices:/docker/abc123\n') is True


def test_detects_containerd_in_cgroup():
	assert _detect_fresh(cgroup_text='0::/system.slice/containerd.service\n') is True


def test_detects_kubepods_in_cgroup():
	assert _detect_fresh(cgroup_text='12:memory:/kubepods/burstable/pod-xyz\n') is True


def test_detects_podman_containerenv():
	assert _detect_fresh(containerenv_exists=True) is True


def test_detects_container_env_var():
	assert _detect_fresh(env_vars={'container': 'lxc'}) is True


def test_detects_kubernetes_env_var():
	assert _detect_fresh(env_vars={'KUBERNETES_SERVICE_HOST': '10.0.0.1'}) is True


def test_detects_low_process_count():
	assert _detect_fresh(pid_count=5) is True


# ---------------------------------------------------------------------------
# Negative signals — bare-metal system should return False
# ---------------------------------------------------------------------------


def test_bare_metal_returns_false():
	"""No container signals present → not in Docker."""
	assert _detect_fresh() is False


def test_many_processes_alone_not_enough():
	"""High process count with no other signals → not in Docker."""
	assert _detect_fresh(pid_count=200) is False


# ---------------------------------------------------------------------------
# Regression: PID 1 substring matching false positives (issue #4149)
# ---------------------------------------------------------------------------


def test_no_false_positive_from_pid1_python():
	"""PID 1 running Python (e.g. bare-metal uWSGI) must NOT trigger detection."""
	# The old code matched 'py' as a substring of the PID 1 command,
	# producing false positives on bare-metal Linux servers running
	# Python-based services as PID 1 (systemd unit with ExecStart=python).
	assert _detect_fresh(pid1_cmdline=['/usr/bin/python3', '/opt/myapp/server.py'], pid_count=50) is False


def test_no_false_positive_from_pid1_uv():
	"""PID 1 running uv must NOT trigger detection."""
	assert _detect_fresh(pid1_cmdline=['/usr/local/bin/uv', 'run', 'serve'], pid_count=50) is False


def test_no_false_positive_from_pid1_app_path():
	"""PID 1 with 'app' in the path must NOT trigger detection."""
	assert _detect_fresh(pid1_cmdline=['/opt/application/start.sh'], pid_count=50) is False
