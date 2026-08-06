"""Regression: ignore_default_args as a list must preserve CHROME_DEFAULT_ARGS order."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile


def _default_args_in_order(args: list[str], ignore: list[str]) -> tuple[list[str], list[str]]:
	"""Return (seen_in_args, expected) for whole-token CHROME_DEFAULT_ARGS entries.

	`--disable-features=...` is merged later in get_args(), so it may not appear as the
	original token. We only track whole-token defaults that survive unchanged.
	"""
	ignored = set(ignore)
	expected = [arg for arg in CHROME_DEFAULT_ARGS if arg not in ignored and not arg.startswith('--disable-features=')]
	# Preserve first-seen order from the final args list, restricted to expected defaults.
	seen: list[str] = []
	expected_set = set(expected)
	for arg in args:
		if arg in expected_set and arg not in seen:
			seen.append(arg)
	return seen, expected


class TestGetArgsDefaultOrder:
	def test_ignore_default_args_list_preserves_chrome_default_order(self):
		"""List ignore mode should filter defaults without set-driven reordering."""
		ignore = ['--disable-popup-blocking', '--metrics-recording-only']
		assert all(arg in CHROME_DEFAULT_ARGS for arg in ignore)

		profile = BrowserProfile(
			ignore_default_args=ignore,
			user_data_dir=tempfile.mkdtemp(prefix='test-default-order-'),
			headless=True,
			enable_default_extensions=False,
		)
		profile.detect_display_configuration()
		args = profile.get_args()

		seen, expected = _default_args_in_order(args, ignore)
		assert seen == expected
		for ignored in ignore:
			assert ignored not in args

	def test_ignore_default_args_list_order_stable_across_hash_seeds(self):
		"""Order must not depend on PYTHONHASHSEED (set iteration used to shuffle it)."""
		repo_root = Path(__file__).resolve().parents[3]
		script = r"""
import tempfile
from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile

ignore = ['--disable-popup-blocking']
profile = BrowserProfile(
    ignore_default_args=ignore,
    user_data_dir=tempfile.mkdtemp(prefix='test-hashseed-'),
    headless=True,
    enable_default_extensions=False,
)
profile.detect_display_configuration()
args = profile.get_args()
ignored = set(ignore)
expected = [
    a for a in CHROME_DEFAULT_ARGS
    if a not in ignored and not a.startswith('--disable-features=')
]
seen = []
expected_set = set(expected)
for arg in args:
    if arg in expected_set and arg not in seen:
        seen.append(arg)
assert seen == expected, (seen, expected)
print('\n'.join(seen))
"""
		env_base = os.environ.copy()
		env_base['PYTHONPATH'] = str(repo_root) + os.pathsep + env_base.get('PYTHONPATH', '')

		outputs = []
		for seed in ('0', '1', '42', '12345'):
			env = env_base.copy()
			env['PYTHONHASHSEED'] = seed
			proc = subprocess.run(
				[sys.executable, '-c', script],
				env=env,
				capture_output=True,
				text=True,
				check=False,
			)
			assert proc.returncode == 0, proc.stderr
			outputs.append(proc.stdout)

		assert len(set(outputs)) == 1, f'get_args order varied across PYTHONHASHSEED values:\n{outputs}'
