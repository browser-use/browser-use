"""Lazy-loading configuration system for browser-use environment variables."""

import os
from functools import cache
from pathlib import Path

import psutil


@cache
def is_running_in_docker() -> bool:
	"""Detect if we are running in a docker container, for the purpose of optimizing chrome launch flags (dev shm usage, gpu settings, etc.)"""
	try:
		if Path('/.dockerenv').exists() or 'docker' in Path('/proc/1/cgroup').read_text().lower():
			return True
	except Exception:
		pass

	try:
		# if init proc (PID 1) looks like uvicorn/python/uv/etc. then we're in Docker
		# if init proc (PID 1) looks like bash/systemd/init/etc. then we're probably NOT in Docker
		init_cmd = ' '.join(psutil.Process(1).cmdline())
		if ('py' in init_cmd) or ('uv' in init_cmd) or ('app' in init_cmd):
			return True
	except Exception:
		pass

	try:
		# if less than 10 total running procs, then we're almost certainly in a container
		if len(psutil.pids()) < 10:
			return True
	except Exception:
		pass

	return False


class Config:
	"""Lazy-loading configuration class for environment variables (env vars can change at runtime so we need to get them fresh on every access)"""

	# Cache for directory creation tracking
	_dirs_created = False

	@property
	def BROWSER_USE_LOGGING_LEVEL(self) -> str:
		return os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info').lower()

	@property
	def ANONYMIZED_TELEMETRY(self) -> bool:
		return os.getenv('ANONYMIZED_TELEMETRY', 'true').lower()[:1] in 'ty1'

	@property
	def BROWSER_USE_CLOUD_SYNC(self) -> bool:
		return os.getenv('BROWSER_USE_CLOUD_SYNC', str(self.ANONYMIZED_TELEMETRY)).lower()[:1] in 'ty1'

	@property
	def BROWSER_USE_CLOUD_API_URL(self) -> str:
		url = os.getenv('BROWSER_USE_CLOUD_API_URL', 'https://api.browser-use.com')
		assert '://' in url, 'BROWSER_USE_CLOUD_API_URL must be a valid URL'
		return url

	@property
	def BROWSER_USE_CLOUD_UI_URL(self) -> str:
		url = os.getenv('BROWSER_USE_CLOUD_UI_URL', '')
		# Allow empty string as default, only validate if set
		if url and '://' not in url:
			raise AssertionError('BROWSER_USE_CLOUD_UI_URL must be a valid URL if set')
		return url

	# Path configuration
	@property
	def XDG_CACHE_HOME(self) -> Path:
		return Path(os.getenv('XDG_CACHE_HOME', '~/.cache')).expanduser().resolve()

	@property
	def XDG_CONFIG_HOME(self) -> Path:
		return Path(os.getenv('XDG_CONFIG_HOME', '~/.config')).expanduser().resolve()

	@property
	def BROWSER_USE_CONFIG_DIR(self) -> Path:
		path = Path(os.getenv('BROWSER_USE_CONFIG_DIR', str(self.XDG_CONFIG_HOME / 'browseruse'))).expanduser().resolve()
		self._ensure_dirs()
		return path

	@property
	def BROWSER_USE_CONFIG_FILE(self) -> Path:
		return self.BROWSER_USE_CONFIG_DIR / 'config.json'

	@property
	def BROWSER_USE_PROFILES_DIR(self) -> Path:
		path = self.BROWSER_USE_CONFIG_DIR / 'profiles'
		self._ensure_dirs()
		return path

	@property
	def BROWSER_USE_DEFAULT_USER_DATA_DIR(self) -> Path:
		return self.BROWSER_USE_PROFILES_DIR / 'default'

	def _ensure_dirs(self) -> None:
		"""Create directories if they don't exist (only once)"""
		if not self._dirs_created:
			config_dir = (
				Path(os.getenv('BROWSER_USE_CONFIG_DIR', str(self.XDG_CONFIG_HOME / 'browseruse'))).expanduser().resolve()
			)
			config_dir.mkdir(parents=True, exist_ok=True)
			(config_dir / 'profiles').mkdir(parents=True, exist_ok=True)
			self._dirs_created = True

	# LLM API key configuration
	@property
	def OPENAI_API_KEY(self) -> str:
		return os.getenv('OPENAI_API_KEY', '')

	@property
	def ANTHROPIC_API_KEY(self) -> str:
		return os.getenv('ANTHROPIC_API_KEY', '')

	@property
	def GOOGLE_API_KEY(self) -> str:
		return os.getenv('GOOGLE_API_KEY', '')

	@property
	def DEEPSEEK_API_KEY(self) -> str:
		return os.getenv('DEEPSEEK_API_KEY', '')

	@property
	def GROK_API_KEY(self) -> str:
		return os.getenv('GROK_API_KEY', '')

	@property
	def NOVITA_API_KEY(self) -> str:
		return os.getenv('NOVITA_API_KEY', '')

	@property
	def AZURE_OPENAI_ENDPOINT(self) -> str:
		return os.getenv('AZURE_OPENAI_ENDPOINT', '')

	@property
	def AZURE_OPENAI_KEY(self) -> str:
		return os.getenv('AZURE_OPENAI_KEY', '')

	@property
	def SKIP_LLM_API_KEY_VERIFICATION(self) -> bool:
		return os.getenv('SKIP_LLM_API_KEY_VERIFICATION', 'false').lower()[:1] in 'ty1'

	# Runtime hints
	@property
	def IN_DOCKER(self) -> bool:
		return os.getenv('IN_DOCKER', 'false').lower()[:1] in 'ty1' or is_running_in_docker()

	@property
	def IS_IN_EVALS(self) -> bool:
		return os.getenv('IS_IN_EVALS', 'false').lower()[:1] in 'ty1'

	@property
	def WIN_FONT_DIR(self) -> str:
		return os.getenv('WIN_FONT_DIR', 'C:\\Windows\\Fonts')


# Create a singleton instance
CONFIG = Config()
