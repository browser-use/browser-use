"""Environment settings read by telemetry and logging."""

import os
from functools import cache
from pathlib import Path


@cache
def is_running_in_docker() -> bool:
	try:
		return Path('/.dockerenv').exists() or 'docker' in Path('/proc/1/cgroup').read_text(encoding='utf-8', errors='replace').lower()
	except Exception:
		return False


class Config:
	"""Reads the environment on every access, so tests and late os.environ changes are respected."""

	@property
	def BROWSER_USE_LOGGING_LEVEL(self) -> str:
		return os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info').lower()

	@property
	def ANONYMIZED_TELEMETRY(self) -> bool:
		return os.getenv('ANONYMIZED_TELEMETRY', 'true').lower()[:1] in 'ty1'

	@property
	def BROWSER_USE_CONFIG_DIR(self) -> Path:
		xdg = Path(os.getenv('XDG_CONFIG_HOME', '~/.config')).expanduser()
		path = Path(os.getenv('BROWSER_USE_CONFIG_DIR', str(xdg / 'browseruse'))).expanduser().resolve()
		path.mkdir(parents=True, exist_ok=True)
		return path


CONFIG = Config()
