from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = 'BrowserBuddy'
BUNDLE_ID = 'com.example.browserbuddystudio'

# Everything the app writes at runtime lives under one folder so that removing
# the app plus this folder (or using 设置 → 彻底删除本地数据) leaves nothing behind.
DEFAULT_APP_SUPPORT_DIR = Path.home() / 'Library' / 'Application Support' / APP_NAME
_DATA_DIR_OVERRIDE = os.environ.get('BROWSER_BUDDY_DATA_DIR')
APP_SUPPORT_DIR = Path(_DATA_DIR_OVERRIDE).expanduser() if _DATA_DIR_OVERRIDE else DEFAULT_APP_SUPPORT_DIR

LOG_DIR = APP_SUPPORT_DIR / 'logs'
PROFILE_DIR = APP_SUPPORT_DIR / 'browser-profile'
ARTIFACT_DIR = APP_SUPPORT_DIR / 'artifacts'
HISTORY_DIR = APP_SUPPORT_DIR / 'history'
BROWSER_STATE_FILE = APP_SUPPORT_DIR / 'storage_state.json'
PLATFORM_LOGINS_FILE = APP_SUPPORT_DIR / 'platform_logins.json'
DOWNLOADS_DIR = APP_SUPPORT_DIR / 'downloads'

# Older builds wrote logs outside the shared folder. Keep upgrading users clean.
LEGACY_LOG_DIR = Path.home() / 'Library' / 'Logs' / APP_NAME
SAVED_STATE_DIR = Path.home() / 'Library' / 'Saved Application State' / f'{BUNDLE_ID}.savedState'
CACHE_DIR = Path.home() / 'Library' / 'Caches' / APP_NAME
WEBKIT_DIR = Path.home() / 'Library' / 'WebKit' / BUNDLE_ID
HTTP_STORAGE_DIR = Path.home() / 'Library' / 'HTTPStorages' / BUNDLE_ID
PREFS_FILE = Path.home() / 'Library' / 'Preferences' / f'{BUNDLE_ID}.plist'

APP_ROOT = Path(__file__).resolve().parent.parent


def frontend_dist() -> Path:
	if getattr(sys, 'frozen', False):
		base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
		return base / 'frontend' / 'dist'
	return APP_ROOT / 'frontend' / 'dist'


def bundled_browser_dir() -> Path | None:
	"""Return the Playwright browser folder shipped inside the .app, if any."""
	if not getattr(sys, 'frozen', False):
		return None
	base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
	candidate = base / 'ms-playwright'
	return candidate if candidate.exists() else None


def bundled_browser_executable() -> str | None:
	"""Find the Chromium binary copied into the app bundle.

	Playwright has shipped both ``Chromium.app`` and, more recently,
	``Google Chrome for Testing.app`` layouts, so accept either.
	"""
	base = bundled_browser_dir()
	if base is None:
		return None
	for pattern in (
		'chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
		'chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
		'chromium_headless_shell-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
	):
		matches = sorted(base.glob(pattern))
		for match in reversed(matches):
			if match.is_file():
				return str(match)
	return None


SYSTEM_BROWSER_PATHS = (
	'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	'/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta',
	'/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
	'/Applications/Chromium.app/Contents/MacOS/Chromium',
	'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
	'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
)


def browser_is_available() -> bool:
	"""True when this Mac can provide a Chromium-based browser."""
	if bundled_browser_executable() is not None:
		return True
	return any(Path(path).is_file() for path in SYSTEM_BROWSER_PATHS)


def _migrate_legacy_logs() -> None:
	if not LEGACY_LOG_DIR.exists():
		return
	try:
		LOG_DIR.mkdir(parents=True, exist_ok=True)
		for item in LEGACY_LOG_DIR.iterdir():
			target = LOG_DIR / item.name
			if target.exists():
				continue
			shutil.move(str(item), str(target))
		shutil.rmtree(LEGACY_LOG_DIR, ignore_errors=True)
	except Exception:
		# Logging setup must never block startup.
		pass


def prepare_runtime() -> None:
	APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	PROFILE_DIR.mkdir(parents=True, exist_ok=True)
	ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
	HISTORY_DIR.mkdir(parents=True, exist_ok=True)
	DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
	_migrate_legacy_logs()

	if getattr(sys, 'frozen', False):
		bundled_chromium = bundled_browser_dir()
		if bundled_chromium is not None:
			# The browser shipped inside this .app always wins over a stale
			# PLAYWRIGHT_BROWSERS_PATH inherited from the user's shell.
			os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled_chromium)

		log_file = (LOG_DIR / 'studio.log').open('a', buffering=1)
		sys.stdout = log_file
		sys.stderr = log_file


def delete_local_data() -> None:
	"""Delete every file the app owns outside the .app bundle.

	The running process keeps its open log handle, so the folder may briefly
	reappear on disk until the app exits. Call this right before quitting.
	"""
	for path in (
		APP_SUPPORT_DIR,
		LEGACY_LOG_DIR,
		SAVED_STATE_DIR,
		CACHE_DIR,
		WEBKIT_DIR,
		HTTP_STORAGE_DIR,
	):
		shutil.rmtree(path, ignore_errors=True)
	PREFS_FILE.unlink(missing_ok=True)
