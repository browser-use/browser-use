"""Environment settings read by telemetry and logging, and .env loading for the parent process."""

import os
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

# BROWSER_USE_OFFLINE=1 also turns off browser-harness's own telemetry and update check, in every process it starts
OFFLINE_HARNESS_ENV = {'BH_TELEMETRY': '0', 'BH_UPDATE_CHECK': '0'}


def load_env() -> None:
	"""Read .env from the working directory (or a parent) into os.environ, as 0.x did on import; set variables win.
	Called by the Agent and Browser modules, so credentials resolve from .env. The REPL worker never calls it."""
	from dotenv import find_dotenv, load_dotenv

	load_dotenv(find_dotenv(usecwd=True))


@cache
def is_running_in_docker() -> bool:
	try:
		return (
			Path('/.dockerenv').exists()
			or 'docker' in Path('/proc/1/cgroup').read_text(encoding='utf-8', errors='replace').lower()
		)
	except Exception:
		return False


class Config:
	"""Reads the environment on every access, so tests and late os.environ changes are respected."""

	@property
	def BROWSER_USE_LOGGING_LEVEL(self) -> str:
		return os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info').lower()

	@property
	def BROWSER_USE_OFFLINE(self) -> bool:
		"""Nothing goes to Browser Use (MIGRATING.md "Network inventory"): only your model endpoint and your browser."""
		return os.getenv('BROWSER_USE_OFFLINE', '').strip().lower() in ('1', 'true', 'yes', 'on')

	@property
	def ANONYMIZED_TELEMETRY(self) -> bool:
		if self.BROWSER_USE_OFFLINE:
			return False
		value = os.getenv('ANONYMIZED_TELEMETRY', 'true').strip().lower()
		return value != '' and value[0] in 'ty1'  # '' in 'ty1' is True: an empty value left telemetry on

	@property
	def BROWSER_USE_CONFIG_DIR(self) -> Path:
		xdg = Path(os.getenv('XDG_CONFIG_HOME', '~/.config')).expanduser()
		path = Path(os.getenv('BROWSER_USE_CONFIG_DIR', str(xdg / 'browseruse'))).expanduser().resolve()
		path.mkdir(parents=True, exist_ok=True)
		return path


CONFIG = Config()


def is_browser_use_host(url: str) -> bool:
	"""browser-use.com or a subdomain (the gateway, the cloud API, search)."""
	host = (urlparse(url).hostname or '').lower()
	return host == 'browser-use.com' or host.endswith('.browser-use.com')


def check_online(what: str, fix: str) -> None:
	"""With BROWSER_USE_OFFLINE set, refuse what would contact Browser Use, before anything starts."""
	if CONFIG.BROWSER_USE_OFFLINE:
		raise ValueError(f'BROWSER_USE_OFFLINE=1: {what} would contact Browser Use. {fix}, or unset BROWSER_USE_OFFLINE.')


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
