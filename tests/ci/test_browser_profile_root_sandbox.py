import os
import sys

import browser_use.config as browser_use_config
from browser_use.browser import BrowserProfile


def test_browser_profile_disables_sandbox_for_root_on_linux(monkeypatch):
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(os, 'geteuid', lambda: 0)
	monkeypatch.setenv('IN_DOCKER', 'false')
	monkeypatch.setattr(browser_use_config, 'is_running_in_docker', lambda: False)

	profile = BrowserProfile(headless=True, chromium_sandbox=True)

	assert profile.chromium_sandbox is False


def test_browser_profile_only_adds_no_sandbox_for_root_outside_docker(monkeypatch, tmp_path):
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(os, 'geteuid', lambda: 0)
	monkeypatch.setenv('IN_DOCKER', 'false')
	monkeypatch.setattr(browser_use_config, 'is_running_in_docker', lambda: False)

	profile = BrowserProfile(headless=True, chromium_sandbox=True, user_data_dir=tmp_path, enable_default_extensions=False)
	args = profile.get_args()

	assert '--no-sandbox' in args
	assert '--disable-gpu-sandbox' not in args
	assert '--disable-setuid-sandbox' not in args
	assert '--no-xshm' not in args
	assert '--no-zygote' not in args
	assert '--disable-site-isolation-trials' not in args


def test_browser_profile_keeps_sandbox_for_non_root(monkeypatch):
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(os, 'geteuid', lambda: 1000)
	monkeypatch.setenv('IN_DOCKER', 'false')
	monkeypatch.setattr(browser_use_config, 'is_running_in_docker', lambda: False)

	profile = BrowserProfile(headless=True, chromium_sandbox=True)

	assert profile.chromium_sandbox is True
