import os
import sys
from collections.abc import Iterable
from enum import Enum
from functools import cache
from pathlib import Path
from re import Pattern
from typing import Annotated, Any, Self
from urllib.parse import urlparse
from venv import logger

from playwright._impl._api_structures import (
	ClientCertificate,
	Geolocation,
	HttpCredentials,
	ProxySettings,
	StorageState,
	ViewportSize,
)
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from uuid_extensions import uuid7str

# fix pydantic error on python 3.11
# PydanticUserError: Please use `typing_extensions.TypedDict` instead of `typing.TypedDict` on Python < 3.12.
# For further information visit https://errors.pydantic.dev/2.10/u/typed-dict-version
if sys.version_info < (3, 12):
	from typing_extensions import TypedDict

	# convert new-style typing.TypedDict used by playwright to old-style typing_extensions.TypedDict used by pydantic
	ClientCertificate = TypedDict('ClientCertificate', ClientCertificate.__annotations__, total=ClientCertificate.__total__)
	Geolocation = TypedDict('Geolocation', Geolocation.__annotations__, total=Geolocation.__total__)
	ProxySettings = TypedDict('ProxySettings', ProxySettings.__annotations__, total=ProxySettings.__total__)
	ViewportSize = TypedDict('ViewportSize', ViewportSize.__annotations__, total=ViewportSize.__total__)
	HttpCredentials = TypedDict('HttpCredentials', HttpCredentials.__annotations__, total=HttpCredentials.__total__)
	StorageState = TypedDict('StorageState', StorageState.__annotations__, total=StorageState.__total__)

IN_DOCKER = os.environ.get('IN_DOCKER', 'false').lower()[0] in 'ty1'
CHROME_DEBUG_PORT = 9242  # use a non-default port to avoid conflicts with other tools / devs using 9222
CHROME_DISABLED_COMPONENTS = [
	# Playwright defaults: https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts#L76
	# See https:#github.com/microsoft/playwright/pull/10380
	'AcceptCHFrame',
	# See https:#github.com/microsoft/playwright/pull/10679
	'AutoExpandDetailsElement',
	# See https:#github.com/microsoft/playwright/issues/14047
	'AvoidUnnecessaryBeforeUnloadCheckSync',
	# See https:#github.com/microsoft/playwright/pull/12992
	'CertificateTransparencyComponentUpdater',
	'DestroyProfileOnBrowserClose',
	# See https:#github.com/microsoft/playwright/pull/13854
	'DialMediaRouteProvider',
	# Chromium is disabling manifest version 2. Allow testing it as long as Chromium can actually run it.
	# Disabled in https:#chromium-review.googlesource.com/c/chromium/src/+/6265903.
	'ExtensionManifestV2Disabled',
	'GlobalMediaControls',
	# See https:#github.com/microsoft/playwright/pull/27605
	'HttpsUpgrades',
	'ImprovedCookieControls',
	'LazyFrameLoading',
	# Hides the Lens feature in the URL address bar. Its not working in unofficial builds.
	'LensOverlay',
	# See https:#github.com/microsoft/playwright/pull/8162
	'MediaRouter',
	# See https:#github.com/microsoft/playwright/issues/28023
	'PaintHolding',
	# See https:#github.com/microsoft/playwright/issues/32230
	'ThirdPartyStoragePartitioning',
	# See https://github.com/microsoft/playwright/issues/16126
	'Translate',
	'AutomationControlled',
	# Added by us:
	'OptimizationHints',
	'ProcessPerSiteUpToMainFrameThreshold',
	'InterestFeedContentSuggestions',
	'CalculateNativeWinOcclusion',  # chrome normally stops rendering tabs if they are not visible (occluded by a foreground window or other app)
	# 'BackForwardCache',  # agent does actually use back/forward navigation, but we can disable if we ever remove that
	'HeavyAdPrivacyMitigations',
	'PrivacySandboxSettings4',
	'AutofillServerCommunication',
	'CrashReporting',
	'OverscrollHistoryNavigation',
	'InfiniteSessionRestore',
]

CHROME_HEADLESS_ARGS = [
	'--headless=new',
]

CHROME_DOCKER_ARGS = [
	'--no-sandbox',
	'--disable-gpu-sandbox',
	'--disable-setuid-sandbox',
	'--disable-dev-shm-usage',
	'--no-xshm',
]

CHROME_DISABLE_SECURITY_ARGS = [
	'--disable-web-security',
	'--disable-site-isolation-trials',
	'--disable-features=IsolateOrigins,site-per-process',
	'--allow-running-insecure-content',
	'--ignore-certificate-errors',
	'--ignore-ssl-errors',
	'--ignore-certificate-errors-spki-list',
]

CHROME_DETERMINISTIC_RENDERING_ARGS = [
	'--deterministic-mode',
	'--js-flags=--random-seed=1157259159',
	'--force-device-scale-factor=1',
	'--enable-webgl',
	'--font-render-hinting=none',
	'--force-color-profile=srgb',
	'--disable-skia-runtime-opts',
	'--disable-2d-canvas-clip-aa',
]

CHROME_DEFAULT_ARGS = [
	# provided by playwright by default: https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts#L76
	# we don't need to include them twice in our own config
	'--disable-field-trial-config',  # https://source.chromium.org/chromium/chromium/src/+/main:testing/variations/README.md
	'--disable-background-networking',
	'--disable-background-timer-throttling',
	'--disable-backgrounding-occluded-windows',
	'--disable-back-forward-cache',  # Avoids surprises like main request not being intercepted during page.goBack().
	'--disable-breakpad',
	'--disable-client-side-phishing-detection',
	'--disable-component-extensions-with-background-pages',
	'--disable-component-update',  # Avoids unneeded network activity after startup.
	'--no-default-browser-check',
	# '--disable-default-apps',
	'--disable-dev-shm-usage',
	# '--disable-extensions',
	# '--disable-features=' + disabledFeatures(assistantMode).join(','),
	'--allow-pre-commit-input',
	'--disable-hang-monitor',
	'--disable-ipc-flooding-protection',
	'--disable-popup-blocking',
	'--disable-prompt-on-repost',
	'--disable-renderer-backgrounding',
	'--force-color-profile=srgb',
	'--metrics-recording-only',
	'--no-first-run',
	'--password-store=basic',
	'--use-mock-keychain',
	# // See https://chromium-review.googlesource.com/c/chromium/src/+/2436773
	'--no-service-autorun',
	'--export-tagged-pdf',
	# // https://chromium-review.googlesource.com/c/chromium/src/+/4853540
	'--disable-search-engine-choice-screen',
	# // https://issues.chromium.org/41491762
	'--unsafely-disable-devtools-self-xss-warnings',
	'--enable-features=NetworkService,NetworkServiceInProcess',
	# added by us:
	'--test-type=gpu',
	'--disable-sync',
	'--allow-legacy-extension-manifests',
	'--allow-pre-commit-input',
	'--disable-blink-features=AutomationControlled',
	'--install-autogenerated-theme=0,0,0',
	'--hide-scrollbars',
	'--log-level=2',
	# '--enable-logging=stderr',
	'--disable-focus-on-load',
	'--disable-window-activation',
	'--generate-pdf-document-outline',
	'--no-pings',
	'--ash-no-nudges',
	'--disable-infobars',
	'--simulate-outdated-no-au="Tue, 31 Dec 2099 23:59:59 GMT"',
	'--hide-crash-restore-bubble',
	'--suppress-message-center-popups',
	'--disable-domain-reliability',
	'--disable-datasaver-prompt',
	'--disable-speech-synthesis-api',
	'--disable-speech-api',
	'--disable-print-preview',
	'--safebrowsing-disable-auto-update',
	'--disable-external-intent-requests',
	'--disable-desktop-notifications',
	'--noerrdialogs',
	'--silent-debugger-extension-api',
	f'--disable-features={",".join(CHROME_DISABLED_COMPONENTS)}',
]


@cache
def get_display_size() -> ViewportSize | None:
	# macOS
	try:
		from AppKit import NSScreen

		screen = NSScreen.mainScreen().frame()
		return ViewportSize(width=int(screen.size.width), height=int(screen.size.height))
	except Exception:
		pass

	# Windows & Linux
	try:
		from screeninfo import get_monitors

		monitors = get_monitors()
		monitor = monitors[0]
		return ViewportSize(width=int(monitor.width), height=int(monitor.height))
	except Exception:
		pass

	return None


def get_window_adjustments() -> tuple[int, int]:
	"""Returns recommended x, y offsets for window positioning"""

	if sys.platform == 'darwin':  # macOS
		return -4, 24  # macOS has a small title bar, no border
	elif sys.platform == 'win32':  # Windows
		return -8, 0  # Windows has a border on the left
	else:  # Linux
		return 0, 0


# ===== Validator functions =====

BROWSERUSE_CONFIG_DIR = Path('~/.config/browseruse')
BROWSERUSE_PROFILES_DIR = BROWSERUSE_CONFIG_DIR / 'profiles'


def validate_url(url: str, schemes: Iterable[str] = ()) -> str:
	"""Validate URL format and optionally check for specific schemes."""
	parsed_url = urlparse(url)
	if not parsed_url.netloc:
		raise ValueError(f'Invalid URL format: {url}')
	if schemes and parsed_url.scheme and parsed_url.scheme.lower() not in schemes:
		raise ValueError(f'URL has invalid scheme: {url} (expected one of {schemes})')
	return url


def validate_float_range(value: float, min_val: float, max_val: float) -> float:
	"""Validate that float is within specified range."""
	if not min_val <= value <= max_val:
		raise ValueError(f'Value {value} outside of range {min_val}-{max_val}')
	return value


def validate_cli_arg(arg: str) -> str:
	"""Validate that arg is a valid CLI argument."""
	if not arg.startswith('--'):
		raise ValueError(f'Invalid CLI argument: {arg} (should start with --, e.g. --some-key="some value here")')
	return arg


# ===== Enum definitions =====


class ColorScheme(str, Enum):
	LIGHT = 'light'
	DARK = 'dark'
	NO_PREFERENCE = 'no-preference'
	NULL = 'null'


class Contrast(str, Enum):
	NO_PREFERENCE = 'no-preference'
	MORE = 'more'
	NULL = 'null'


class ReducedMotion(str, Enum):
	REDUCE = 'reduce'
	NO_PREFERENCE = 'no-preference'
	NULL = 'null'


class ForcedColors(str, Enum):
	ACTIVE = 'active'
	NONE = 'none'
	NULL = 'null'


class ServiceWorkers(str, Enum):
	ALLOW = 'allow'
	BLOCK = 'block'


class RecordHarContent(str, Enum):
	OMIT = 'omit'
	EMBED = 'embed'
	ATTACH = 'attach'


class RecordHarMode(str, Enum):
	FULL = 'full'
	MINIMAL = 'minimal'


class BrowserChannel(str, Enum):
	CHROMIUM = 'chromium'
	CHROME = 'chrome'
	CHROME_BETA = 'chrome-beta'
	CHROME_DEV = 'chrome-dev'
	CHROME_CANARY = 'chrome-canary'
	MSEDGE = 'msedge'
	MSEDGE_BETA = 'msedge-beta'
	MSEDGE_DEV = 'msedge-dev'
	MSEDGE_CANARY = 'msedge-canary'


# ===== Type definitions with validators =====

UrlStr = Annotated[str, AfterValidator(validate_url)]
NonNegativeFloat = Annotated[float, AfterValidator(lambda x: validate_float_range(x, 0, float('inf')))]
CliArgStr = Annotated[str, AfterValidator(validate_cli_arg)]


# ===== Base Models =====


class BrowserContextArgs(BaseModel):
	"""
	Base model for common browser context parameters used by
	both new_context() and launch_persistent_context().

	https://playwright.dev/python/docs/api/class-browser#browser-new-context
	"""

	model_config = ConfigDict(extra='ignore', validate_assignment=False, revalidate_instances='always')

	# Browser context parameters
	accept_downloads: bool = True
	offline: bool = False
	strict_selectors: bool = False

	# Security options
	proxy: ProxySettings | None = None
	permissions: list[str] = Field(
		default_factory=lambda: ['clipboard-read', 'clipboard-write'], description='Browser permissions to grant.'
	)
	bypass_csp: bool = False
	client_certificates: list[ClientCertificate] = Field(default_factory=list)
	extra_http_headers: dict[str, str] = Field(default_factory=dict)
	http_credentials: HttpCredentials | None = None
	ignore_https_errors: bool = False
	java_script_enabled: bool = True
	base_url: UrlStr | None = None
	service_workers: ServiceWorkers = ServiceWorkers.ALLOW

	# Viewport options
	user_agent: str | None = None
	screen: ViewportSize | None = None
	viewport: ViewportSize | None = Field(default=None)
	no_viewport: bool | None = None
	device_scale_factor: NonNegativeFloat | None = None
	is_mobile: bool = False
	has_touch: bool = False
	locale: str | None = None
	geolocation: Geolocation | None = None
	timezone_id: str | None = None
	color_scheme: ColorScheme = ColorScheme.LIGHT
	contrast: Contrast = Contrast.NO_PREFERENCE
	reduced_motion: ReducedMotion = ReducedMotion.NO_PREFERENCE
	forced_colors: ForcedColors = ForcedColors.NONE

	# Recording Options
	record_har_content: RecordHarContent = RecordHarContent.EMBED
	record_har_mode: RecordHarMode = RecordHarMode.FULL
	record_har_omit_content: bool = False
	record_har_path: str | Path | None = None
	record_har_url_filter: str | Pattern | None = None
	record_video_dir: str | Path | None = None
	record_video_size: ViewportSize | None = None


class BrowserConnectArgs(BaseModel):
	"""
	Base model for common browser connect parameters used by
	both connect_over_cdp() and connect_over_ws().

	https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect
	https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp
	"""

	model_config = ConfigDict(extra='ignore', validate_assignment=True, revalidate_instances='always')

	headers: dict[str, str] = Field(default_factory=dict)
	slow_mo: float = 0.0
	timeout: float = 30_000


class BrowserLaunchArgs(BaseModel):
	"""
	Base model for common browser launch parameters used by
	both launch() and launch_persistent_context().

	https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch
	"""

	model_config = ConfigDict(
		extra='ignore',
		validate_assignment=True,
		revalidate_instances='always',
		from_attributes=True,
		validate_by_name=True,
		validate_by_alias=True,
	)

	env: dict[str, str | float | bool] = Field(default_factory=dict)
	executable_path: str | Path | None = Field(default=None, validation_alias='chrome_binary_path')
	headless: bool | None = None
	args: list[CliArgStr] = Field(default_factory=list)
	ignore_default_args: list[CliArgStr] = Field(
		default_factory=lambda: ['--enable-automation'],
		description='List of default CLI args to stop playwright from applying (see https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts)',
	)
	channel: BrowserChannel = BrowserChannel.CHROMIUM
	chromium_sandbox: bool = False
	devtools: bool = False
	slow_mo: float = 0
	timeout: float = 30000
	proxy: ProxySettings | None = None
	downloads_path: str | Path | None = None
	traces_dir: str | Path | None = None
	handle_sighup: bool = True
	handle_sigint: bool = True
	handle_sigterm: bool = True
	# firefox_user_prefs: dict[str, str | float | bool] = Field(default_factory=dict)

	@model_validator(mode='after')
	def validate_devtools_headless(self) -> Self:
		"""Cannot open devtools when headless is True"""
		assert not (self.headless and self.devtools), 'headless=True and devtools=True cannot both be set at the same time'
		return self

	@staticmethod
	def args_as_dict(args: list[str]) -> dict[str, str]:
		"""Return the extra launch CLI args as a dictionary."""
		args_dict = {}
		for arg in args:
			key, value, *_ = [*arg.split('=', 1), '', '', '']
			args_dict[key.strip().lstrip('-')] = value.strip()
		return args_dict

	@staticmethod
	def args_as_list(args: dict[str, str]) -> list[str]:
		"""Return the extra launch CLI args as a list of strings."""
		return [f'--{key.lstrip("-")}={value}' if value else f'--{key.lstrip("-")}' for key, value in args.items()]


# ===== API-specific Models =====


class BrowserNewContextArgs(BrowserContextArgs):
	"""
	Pydantic model for new_context() arguments.
	Extends BaseContextParams with storage_state parameter.

	https://playwright.dev/python/docs/api/class-browser#browser-new-context
	"""

	# storage_state is not supported in launch_persistent_context()
	storage_state: str | Path | dict[str, Any] | None = None
	# TODO: use StorageState type

	# to apply this to existing contexts (incl cookies, localStorage, IndexedDB), see:
	# - https://github.com/microsoft/playwright/pull/34591/files
	# - playwright-core/src/server/storageScript.ts restore() function
	# - https://github.com/Skn0tt/playwright/blob/c446bc44bac4fbfdf52439ba434f92192459be4e/packages/playwright-core/src/server/storageScript.ts#L84C1-L123C2

	# @field_validator('storage_state', mode='after')
	# def load_storage_state_from_file(self) -> Self:
	# 	"""Load storage_state from file if it's a path."""
	# 	if isinstance(self.storage_state, (str, Path)):
	# 		storage_state_file = Path(self.storage_state)
	# 		try:
	# 			parsed_storage_state = json.loads(storage_state_file.read_text())
	# 			validated_storage_state = StorageState(**parsed_storage_state)
	# 			self.storage_state = validated_storage_state
	# 		except Exception as e:
	# 			raise ValueError(f'Failed to load storage state file {self.storage_state}: {e}') from e
	# 	return self
	pass


class BrowserLaunchPersistentContextArgs(BrowserLaunchArgs, BrowserContextArgs):
	"""
	Pydantic model for launch_persistent_context() arguments.
	Combines browser launch parameters and context parameters,
	plus adds the user_data_dir parameter.

	https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
	"""

	# Required parameter specific to launch_persistent_context
	user_data_dir: str | Path = BROWSERUSE_PROFILES_DIR / 'default'

	# @field_validator('user_data_dir', mode='after')
	# def validate_user_data_dir(self) -> Self:
	# 	"""Ensure that user_data_dir is a valid path."""

	# 	self.user_data_dir = Path(self.user_data_dir).expanduser().resolve()
	# 	self.user_data_dir.mkdir(parents=True, exist_ok=True)

	# 	# check if they passed a chrome profile subdir by accident
	# 	if (self.user_data_dir / 'History').is_file() and (self.user_data_dir / 'Cookies').is_file():
	# 		raise ValueError(
	# 			f'user_data_dir={self.user_data_dir} is incorrect, you should pass the parent dir instead: {self.user_data_dir.parent}'
	# 		)

	# 	launch_args = self.args or []
	# 	launch_args.append('--no-default-browser-check')
	# 	launch_args.append('--disable-first-run-ui')

	# 	# check if the user_data_dir is initialized
	# 	if (self.user_data_dir / 'Local State').is_file() and (self.user_data_dir / self.profile_directory).is_dir():
	# 		# profile dir already exists and is fully set up, skip first-run inits
	# 		launch_args.append('--no-first-run')
	# 		self._user_data_dir_is_initialized = True
	# 	else:
	# 		# profile dir is empty or has not been initialized yet, it's our first run
	# 		self._user_data_dir_is_initialized = False
	# 		if self.ignore_default_args is not True:
	# 			self.ignore_default_args = (self.ignore_default_args or []).append('--no-first-run')

	# 	# assignment is required to re-trigger the args field validator
	# 	self.args = launch_args

	# 	return self


class BrowserProfile(BrowserConnectArgs, BrowserLaunchPersistentContextArgs, BrowserLaunchArgs, BrowserNewContextArgs):
	"""
	A BrowserProfile is a static collection of kwargs that get passed to:
		- BrowserType.launch(**BrowserLaunchArgs)
		- BrowserType.connect(**BrowserConnectArgs)
		- BrowserType.connect_over_cdp(**BrowserConnectArgs)
		- BrowserType.launch_persistent_context(**BrowserLaunchPersistentContextArgs)
		- BrowserContext.new_context(**BrowserNewContextArgs)
		- BrowserSession(**BrowserProfile)
	"""

	model_config = ConfigDict(
		extra='ignore',
		validate_assignment=True,
		revalidate_instances='always',
		from_attributes=True,
		validate_by_name=True,
		validate_by_alias=True,
	)

	id: str = Field(default_factory=uuid7str)
	label: str = 'default'

	# custom options we provide that aren't native playwright kwargs
	disable_security: bool = Field(default=False, description='Disable browser security features.')
	deterministic_rendering: bool = Field(default=False, description='Enable deterministic rendering flags.')
	allowed_domains: list[str] | None = Field(default=None, description='List of allowed domains for navigation.')
	keep_alive: bool | None = Field(default=None, description='Keep browser alive after agent run.')
	window_size: ViewportSize | None = Field(
		default=None,
		description='Window size to use for the browser when headless=False.',
	)
	window_position: ViewportSize | None = Field(
		default_factory=lambda: {'width': 0, 'height': 0},
		description='Window position to use for the browser x,y from the top left when headless=False.',
	)

	# --- Page load/wait timings ---
	minimum_wait_page_load_time: float = Field(default=0.25, description='Minimum time to wait before capturing page state.')
	wait_for_network_idle_page_load_time: float = Field(default=0.5, description='Time to wait for network idle.')
	maximum_wait_page_load_time: float = Field(default=5.0, description='Maximum time to wait for page load.')
	wait_between_actions: float = Field(default=0.5, description='Time to wait between actions.')

	# --- UI/viewport/DOM ---
	include_dynamic_attributes: bool = Field(default=True, description='Include dynamic attributes in selectors.')
	highlight_elements: bool = Field(default=True, description='Highlight interactive elements on the page.')
	viewport_expansion: int = Field(default=500, description='Viewport expansion in pixels for LLM context.')

	profile_directory: str = 'Default'  # e.g. 'Profile 1', 'Profile 2', 'Custom Profile', etc.

	save_recording_path: str | None = Field(default=None, description='Directory for video recordings.')
	save_downloads_path: str | None = Field(default=None, description='Directory for saving downloads.')
	save_har_path: str | None = Field(default=None, description='Directory for saving HAR files.')
	trace_path: str | None = Field(default=None, description='Directory for saving trace files.')

	# extension_ids_to_preinstall: list[str] = Field(
	# 	default_factory=list, description='List of Chrome extension IDs to preinstall.'
	# )
	# extensions_dir: Path = Field(
	# 	default_factory=lambda: Path('~/.config/browseruse/cache/extensions').expanduser(),
	# 	description='Directory containing .crx extension files.',
	# )

	# # --- File paths ---
	# downloads_dir: Path = Field(
	# 	default_factory=lambda: Path('~/.config/browseruse/profiles/default/downloads').expanduser(),
	# 	description='Directory for downloads.',
	# )
	# uploads_dir: Path | None = Field(default=None, description='Directory for uploads (defaults to downloads_dir if not set).')

	def __repr__(self) -> str:
		return f'BrowserProfile(label={self.label})'

	def __str__(self) -> str:
		return repr(self)

	def get_args(self) -> list[str]:
		return BrowserLaunchArgs.args_as_list(  # convert back to ['--arg=value', '--arg', '--arg=value', ...]
			BrowserLaunchArgs.args_as_dict(  # uniquify via dict {'arg': 'value', 'arg2': 'value2', ...}
				[
					*CHROME_DEFAULT_ARGS,
					*self.args,
					f'--profile-directory={self.profile_directory}',
					*(CHROME_DOCKER_ARGS if IN_DOCKER else []),
					*(CHROME_HEADLESS_ARGS if self.headless else []),
					*(CHROME_DISABLE_SECURITY_ARGS if self.disable_security else []),
					*(CHROME_DETERMINISTIC_RENDERING_ARGS if self.deterministic_rendering else []),
					*(
						[f'--window-size={self.window_size["height"]},{self.window_size["width"]}']
						if self.window_size
						else (['--start-maximized' if not self.headless else []])
					),
					*(
						[f'--window-position={self.window_position["width"]},{self.window_position["height"]}']
						if self.window_position
						else []
					),
				]
			)
		)

	def kwargs_for_launch_persistent_context(self) -> BrowserLaunchPersistentContextArgs:
		"""Return the kwargs for BrowserType.launch()."""
		return BrowserLaunchPersistentContextArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	def kwargs_for_new_context(self) -> BrowserNewContextArgs:
		"""Return the kwargs for BrowserContext.new_context()."""
		return BrowserNewContextArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	def kwargs_for_connect(self) -> BrowserConnectArgs:
		"""Return the kwargs for BrowserType.connect()."""
		return BrowserConnectArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	def kwargs_for_launch(self) -> BrowserLaunchArgs:
		"""Return the kwargs for BrowserType.connect_over_cdp()."""
		return BrowserLaunchArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	def prepare_user_data_dir(self) -> None:
		"""Create and unlock the user data dir for first-run initialization."""

		if self.user_data_dir:
			self.user_data_dir = Path(self.user_data_dir).expanduser().resolve()
			self.user_data_dir.mkdir(parents=True, exist_ok=True)

			# clear any existing locks by any other chrome processes
			# hacky way to prevent chrome crashes from leaving dirs locked,
			# but can cause conflicts if they are actually running)
			singleton_lock = self.user_data_dir / 'SingletonLock'
			if singleton_lock.exists():
				singleton_lock.unlink()
				logger.warning(
					f'⚠️ Multiple chrome processes may be trying to share user_data_dir={self.user_data_dir} which can lead to crashes and profile data corruption!'
				)

	def detect_display_configuration(self) -> None:
		"""Detect the display size and set the screen option."""

		display_size = get_display_size()
		if display_size:
			self.screen = self.screen or display_size or ViewportSize(width=1280, height=1100)

		# if no headless preference specified, prefer headful if there is a display available
		if self.headless is None:
			self.headless = not bool(display_size)

		# set up window size and position if headful
		if self.headless:
			# headless mode: no window available, use viewport instead to constrain content size
			self.window_size = None
			self.window_position = None
			self.no_viewport = False
			self.viewport = self.viewport or display_size or ViewportSize(width=1280, height=1100)
		else:
			# headful mode: use window, disable viewport, content fits to size of window
			self.window_size = self.window_size or display_size or ViewportSize(width=1280, height=1100)
			self.no_viewport = True if self.no_viewport is None else self.no_viewport
			self.viewport = None if self.no_viewport else self.viewport

		# automatically setup viewport if any config requires it
		use_viewport = self.headless or self.viewport or self.device_scale_factor
		self.no_viewport = not use_viewport if self.no_viewport is None else self.no_viewport
		if use_viewport:
			self.viewport = self.viewport or display_size or ViewportSize(width=1280, height=1100)
			self.device_scale_factor = self.device_scale_factor or 1.0
			self.screen = self.screen or display_size or ViewportSize(width=1280, height=1100)
		else:
			self.viewport = None
			self.device_scale_factor = None
			self.screen = None


# For convenience, example function signatures:
"""
def launch(
    **kwargs: Unpack[LaunchArgs]
) -> Browser:
    ...

def new_context(
    **kwargs: Unpack[NewContextArgs]
) -> BrowserContext:
    ...

def launch_persistent_context(
    user_data_dir: str | Path,
    **kwargs: Unpack[LaunchPersistentContextArgs]
) -> BrowserContext:
    ...
"""
