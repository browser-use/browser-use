from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .config import APP_SUPPORT_DIR, HISTORY_DIR

HISTORY_FILE = HISTORY_DIR / 'history.json'
PREFERENCES_FILE = APP_SUPPORT_DIR / 'preferences.json'
_LOCK = threading.Lock()


def _read_json(path: Path, default: Any) -> Any:
	try:
		return json.loads(path.read_text(encoding='utf-8'))
	except Exception:
		return default


def _write_json(path: Path, data: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temp = path.with_suffix(path.suffix + '.tmp')
	temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
	temp.replace(path)


def load_history() -> list[dict]:
	with _LOCK:
		value = _read_json(HISTORY_FILE, [])
	return value if isinstance(value, list) else []


def add_history(entry: dict) -> list[dict]:
	with _LOCK:
		items = _read_json(HISTORY_FILE, [])
		if not isinstance(items, list):
			items = []
		entry_id = entry.get('id')
		items = [item for item in items if item.get('id') != entry_id]
		items.insert(0, entry)
		items = items[:20]
		_write_json(HISTORY_FILE, items)
	return items


def clear_history() -> None:
	with _LOCK:
		_write_json(HISTORY_FILE, [])


def load_preferences() -> dict:
	with _LOCK:
		value = _read_json(PREFERENCES_FILE, {})
	return value if isinstance(value, dict) else {}


def save_preferences(preferences: dict) -> dict:
	with _LOCK:
		_write_json(PREFERENCES_FILE, preferences)
	return preferences
