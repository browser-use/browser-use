"""CLI configuration schema and helpers.

Single source of truth for all CLI config keys. Doctor, setup, and
getter functions all reference CONFIG_KEYS.
"""

import json
from pathlib import Path

CLI_DOCS_URL = 'https://docs.browser-use.com/open-source/browser-use-cli'

CONFIG_KEYS: dict = {
	'api_key': {
		'type': str,
		'sensitive': True,
		'description': 'Browser Use Cloud API key',
	},
	'cloud_connect_profile_id': {
		'type': str,
		'description': 'Cloud browser profile ID (auto-created)',
	},
	'cloud_connect_proxy': {
		'type': str,
		'default': 'us',
		'description': 'Cloud proxy country code',
	},
	'cloud_connect_timeout': {
		'type': int,
		'description': 'Cloud browser timeout (minutes)',
	},
	'cloud_connect_recording': {
		'type': bool,
		'default': True,
		'description': 'Enable session recording in cloud browser',
	},
}


def _get_config_path() -> Path:
	from browser_use.skill_cli.utils import get_config_path

	return get_config_path()


def read_config() -> dict:
	"""Read CLI config file. Returns empty dict if missing or corrupt."""
	path = _get_config_path()
	if path.exists():
		try:
			return json.loads(path.read_text())
		except (json.JSONDecodeError, OSError):
			return {}
	return {}


def write_config(data: dict) -> None:
	"""Write CLI config file with 0o600 permissions, atomically via tmp+rename.

	Writing directly to config.json risks truncation if the process is killed
	mid-write, which read_config() would silently treat as {} (empty config),
	wiping the API key and all other settings.
	"""
	import os
	import tempfile

	path = _get_config_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	content = json.dumps(data, indent=2) + '\n'

	# Write to a temp file in the same directory so os.replace() is atomic
	# (same filesystem guaranteed — cross-device rename raises OSError).
	fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix='.config_tmp_')
	tmp_path = Path(tmp_str)
	try:
		with os.fdopen(fd, 'w') as f:
			f.write(content)
			f.flush()
			os.fsync(f.fileno())
		try:
			tmp_path.chmod(0o600)
		except OSError:
			pass
		os.replace(tmp_path, path)
	except Exception:
		tmp_path.unlink(missing_ok=True)
		raise


def get_config_value(key: str) -> str | int | None:
	"""Read a config value, applying schema defaults.

	Priority: config file → schema default → None.
	"""
	schema = CONFIG_KEYS.get(key)
	if schema is None:
		return None

	config = read_config()
	val = config.get(key)
	if val is not None:
		return val

	return schema.get('default')


def set_config_value(key: str, value: str) -> None:
	"""Set a config value. Validates key and coerces type."""
	schema = CONFIG_KEYS.get(key)
	if schema is None:
		raise ValueError(f'Unknown config key: {key}. Valid keys: {", ".join(CONFIG_KEYS)}')

	# Coerce type
	expected_type = schema.get('type', str)
	try:
		if expected_type is int:
			coerced = int(value)
		elif expected_type is bool:
			if value.lower() in ('true', '1', 'yes'):
				coerced = True
			elif value.lower() in ('false', '0', 'no'):
				coerced = False
			else:
				raise ValueError(f'Invalid value for {key}: expected true/false, got {value!r}')
		else:
			coerced = str(value)
	except (ValueError, TypeError):
		raise ValueError(f'Invalid value for {key}: expected {expected_type.__name__}, got {value!r}')

	config = read_config()
	config[key] = coerced
	write_config(config)


def unset_config_value(key: str) -> None:
	"""Remove a config key from the file."""
	schema = CONFIG_KEYS.get(key)
	if schema is None:
		raise ValueError(f'Unknown config key: {key}. Valid keys: {", ".join(CONFIG_KEYS)}')

	config = read_config()
	if key in config:
		del config[key]
		write_config(config)


def get_config_display() -> list[dict]:
	"""Return config state for display (doctor, setup).

	Each entry: {key, value, is_set, sensitive, description}
	"""
	config = read_config()
	entries = []
	for key, schema in CONFIG_KEYS.items():
		val = config.get(key)
		is_set = val is not None

		# Apply default for display
		display_val = val
		if not is_set and 'default' in schema:
			display_val = f'{schema["default"]} (default)'

		entries.append(
			{
				'key': key,
				'value': display_val,
				'is_set': is_set,
				'sensitive': schema.get('sensitive', False),
				'description': schema.get('description', ''),
			}
		)
	return entries
