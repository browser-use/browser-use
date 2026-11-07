from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = 'BrowserBuddy'
APP_SUPPORT_DIR = Path.home() / 'Library' / 'Application Support' / APP_NAME
LOG_DIR = Path.home() / 'Library' / 'Logs' / APP_NAME
PROFILE_DIR = APP_SUPPORT_DIR / 'browser-profile'
ARTIFACT_DIR = APP_SUPPORT_DIR / 'artifacts'
HISTORY_DIR = APP_SUPPORT_DIR / 'history'
BROWSER_STATE_FILE = APP_SUPPORT_DIR / 'storage_state.json'
DOWNLOADS_DIR = Path.home() / 'Downloads'

APP_ROOT = Path(__file__).resolve().parent.parent


def frontend_dist() -> Path:
	if getattr(sys, 'frozen', False):
		base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
		return base / 'frontend' / 'dist'
	return APP_ROOT / 'frontend' / 'dist'


def prepare_runtime() -> None:
	APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	PROFILE_DIR.mkdir(parents=True, exist_ok=True)
	ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
	HISTORY_DIR.mkdir(parents=True, exist_ok=True)
	DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

	if getattr(sys, 'frozen', False):
		base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
		bundled_chromium = base / 'ms-playwright'
		if bundled_chromium.exists():
			os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(bundled_chromium))

		log_file = (LOG_DIR / 'studio.log').open('a', buffering=1)
		sys.stdout = log_file
		sys.stderr = log_file
