import sys
from collections.abc import Iterable
from enum import Enum
from functools import cache
from pathlib import Path
from re import Pattern
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, model_validator
from uuid_extensions import uuid7str

from browser_use.browser.types import ClientCertificate, Geolocation, HttpCredentials, ProxySettings, ViewportSize
from browser_use.config import CONFIG
from browser_use.observability import observe_debug
from browser_use.utils import _log_pretty_path, logger

CHROME_DEBUG_PORT = 9242  # use a non-default port to avoid conflicts with other tools / devs using 9222
CHROME_DISABLED_COMPONENTS = [
	# Playwright defaults: https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts#L76
	# AcceptCHFrame,AutoExpandDetailsElement,AvoidUnnecessaryBeforeUnloadCheckSync,CertificateTransparencyComponentUpdater,DeferRendererTasksAfterInput,DestroyProfileOnBrowserClose,DialMediaRouteProvider,ExtensionManifestV2Disabled,GlobalMediaControls,HttpsUpgrades,ImprovedCookieControls,LazyFrameLoading,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,Translate
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
	# 3
	# Added by us:
	'AutomationControlled',
	'BackForwardCache',
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
	'ExtensionDisableUnsupportedDeveloper',
]

CHROME_HEADLESS_ARGS = [
	'--headless=new',
]

CHROME_DOCKER_ARGS = [
	# '--disable-gpu',    # GPU is actually supported in headless docker mode now, but sometimes useful to test without it
	'--no-sandbox',
	'--disable-gpu-sandbox',
	'--disable-setuid-sandbox',
	'--disable-dev-shm-usage',
	'--no-xshm',
	'--no-zygote',
	# '--single-process',  # might be the cause of "Target page, context or browser has been closed" errors during CDP page.captureScreenshot https://stackoverflow.com/questions/51629151/puppeteer-protocol-error-page-navigate-target-closed
	'--disable-site-isolation-trials',  # lowers RAM use by 10-16% in docker, but could lead to easier bot blocking if pages can detect it?
]


CHROME_DISABLE_SECURITY_ARGS = [
	'--disable-site-isolation-trials',
	'--disable-web-security',
	'--disable-features=IsolateOrigins,site-per-process',
	'--allow-running-insecure-content',
	'--ignore-certificate-errors',
	'--ignore-ssl-errors',
	'--ignore-certificate-errors-spki-list',
]

CHROME_DETERMINISTIC_RENDERING_ARGS = [
	'--deterministic-mode',
	'--js-flags=--random-seed=1157259159',
	'--force-device-scale-factor=2',
	'--enable-webgl',
	# '--disable-skia-runtime-opts',
	# '--disable-2d-canvas-clip-aa',
	'--font-render-hinting=none',
	'--force-color-profile=srgb',
]

CHROME_DEFAULT_ARGS = [
	# # provided by playwright by default: https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts#L76
	# # we don't need to include them twice in our own config, but it's harmless
	# '--disable-field-trial-config',  # https://source.chromium.org/chromium/chromium/src/+/main:testing/variations/README.md
	# '--disable-background-networking',
	# '--disable-background-timer-throttling',  # agents might be working on background pages if the human switches to another tab
	# '--disable-backgrounding-occluded-windows',  # same deal, agents are often working on backgrounded browser windows
	# '--disable-back-forward-cache',  # Avoids surprises like main request not being intercepted during page.goBack().
	# '--disable-breakpad',
	# '--disable-client-side-phishing-detection',
	# '--disable-component-extensions-with-background-pages',
	# '--disable-component-update',  # Avoids unneeded network activity after startup.
	# '--no-default-browser-check',
	# # '--disable-default-apps',
	# '--disable-dev-shm-usage',  # crucial for docker support, harmless in non-docker environments
	# # '--disable-extensions',
	# # '--disable-features=' + disabledFeatures(assistantMode).join(','),
	# '--allow-pre-commit-input',  # let page JS run a little early before GPU rendering finishes
	# '--disable-hang-monitor',
	# '--disable-ipc-flooding-protection',  # important to be able to make lots of CDP calls in a tight loop
	# '--disable-popup-blocking',
	# '--disable-prompt-on-repost',
	# '--disable-renderer-backgrounding',
	# # '--force-color-profile=srgb',  # moved to CHROME_DETERMINISTIC_RENDERING_ARGS
	# '--metrics-recording-only',
	# '--no-first-run',
	# '--password-store=basic',
	# '--use-mock-keychain',
	# # // See https://chromium-review.googlesource.com/c/chromium/src/+/2436773
	# '--no-service-autorun',
	# '--export-tagged-pdf',
	# # // https://chromium-review.googlesource.com/c/chromium/src/+/4853540
	# '--disable-search-engine-choice-screen',
	# # // https://issues.chromium.org/41491762
	# '--unsafely-disable-devtools-self-xss-warnings',
	# added by us:
	'--enable-features=NetworkService,NetworkServiceInProcess',
	'--enable-network-information-downlink-max',
	'--test-type=gpu',
	'--disable-sync',
	'--allow-legacy-extension-manifests',
	'--allow-pre-commit-input',
	'--disable-blink-features=AutomationControlled',
	'--install-autogenerated-theme=0,0,0',
	# '--hide-scrollbars',                     # leave them visible! the agent uses them to know when it needs to scroll to see more options
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
		from AppKit import NSScreen  # type: ignore[import]

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


# Using constants from central location in browser_use.config
BROWSERUSE_DEFAULT_CHANNEL = BrowserChannel.CHROMIUM


# ===== Type definitions with validators =====

UrlStr = Annotated[str, AfterValidator(validate_url)]
NonNegativeFloat = Annotated[float, AfterValidator(lambda x: validate_float_range(x, 0, float('inf')))]
CliArgStr = Annotated[str, AfterValidator(validate_cli_arg)]


# ===== Base Models =====


class BrowserContextArgs(BaseModel):
	"""
	Base model for common browser context parameters used by
	both BrowserType.new_context() and BrowserType.launch_persistent_context().

	https://playwright.dev/python/docs/api/class-browser#browser-new-context
	"""

	model_config = ConfigDict(extra='ignore', validate_assignment=False, revalidate_instances='always', populate_by_name=True)

	# Browser context parameters
	accept_downloads: bool = True
	offline: bool = False
	strict_selectors: bool = False

	# Security options
	proxy: ProxySettings | None = None
	permissions: list[str] = Field(
		default_factory=lambda: ['clipboard-read', 'clipboard-write', 'notifications'],
		description='Browser permissions to grant (see playwright docs for valid permissions).',
		# clipboard is for google sheets and pyperclip automations
		# notifications are to avoid browser fingerprinting
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
	record_har_path: str | Path | None = Field(default=None, validation_alias=AliasChoices('save_har_path', 'record_har_path'))
	record_har_url_filter: str | Pattern | None = None
	record_video_dir: str | Path | None = Field(
		default=None, validation_alias=AliasChoices('save_recording_path', 'record_video_dir')
	)
	record_video_size: ViewportSize | None = None


class BrowserConnectArgs(BaseModel):
	"""
	Base model for common browser connect parameters used by
	both connect_over_cdp() and connect_over_ws().

	https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect
	https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp
	"""

	model_config = ConfigDict(extra='ignore', validate_assignment=True, revalidate_instances='always', populate_by_name=True)

	headers: dict[str, str] | None = Field(default=None, description='Additional HTTP headers to be sent with connect request')
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
		populate_by_name=True,
	)

	env: dict[str, str | float | bool] | None = Field(
		default=None,
		description='Extra environment variables to set when launching the browser. If None, inherits from the current process.',
	)
	executable_path: str | Path | None = Field(
		default=None,
		validation_alias=AliasChoices('browser_binary_path', 'chrome_binary_path'),
		description='Path to the chromium-based browser executable to use.',
	)
	headless: bool | None = Field(default=None, description='Whether to run the browser in headless or windowed mode.')
	args: list[CliArgStr] = Field(
		default_factory=list, description='List of *extra* CLI args to pass to the browser when launching.'
	)
	ignore_default_args: list[CliArgStr] | Literal[True] = Field(
		default_factory=lambda: [
			'--enable-automation',  # we mask the automation fingerprint via JS and other flags
			'--disable-extensions',  # allow browser extensions
			'--hide-scrollbars',  # always show scrollbars in screenshots so agent knows there is more content below it can scroll down to
			'--disable-features=AcceptCHFrame,AutoExpandDetailsElement,AvoidUnnecessaryBeforeUnloadCheckSync,CertificateTransparencyComponentUpdater,DeferRendererTasksAfterInput,DestroyProfileOnBrowserClose,DialMediaRouteProvider,ExtensionManifestV2Disabled,GlobalMediaControls,HttpsUpgrades,ImprovedCookieControls,LazyFrameLoading,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,Translate',
		],
		description='List of default CLI args to stop playwright from applying (see https://github.com/microsoft/playwright/blob/41008eeddd020e2dee1c540f7c0cdfa337e99637/packages/playwright-core/src/server/chromium/chromiumSwitches.ts)',
	)
	channel: BrowserChannel | None = None  # https://playwright.dev/docs/browsers#chromium-headless-shell
	chromium_sandbox: bool = Field(
		default=not CONFIG.IN_DOCKER, description='Whether to enable Chromium sandboxing (recommended unless inside Docker).'
	)
	devtools: bool = Field(
		default=False, description='Whether to open DevTools panel automatically for every page, only works when headless=False.'
	)
	slow_mo: float = Field(default=0, description='Slow down actions by this many milliseconds.')
	timeout: float = Field(default=30000, description='Default timeout in milliseconds for connecting to a remote browser.')
	proxy: ProxySettings | None = Field(default=None, description='Proxy settings to use to connect to the browser.')
	downloads_path: str | Path | None = Field(
		default=None,
		description='Directory to save downloads to.',
		validation_alias=AliasChoices('downloads_dir', 'save_downloads_path'),
	)
	traces_dir: str | Path | None = Field(
		default=None,
		description='Directory for saving playwright trace.zip files (playwright actions, screenshots, DOM snapshots, HAR traces).',
		validation_alias=AliasChoices('trace_path', 'traces_dir'),
	)
	handle_sighup: bool = Field(
		default=True, description='Whether playwright should swallow SIGHUP signals and kill the browser.'
	)
	handle_sigint: bool = Field(
		default=False, description='Whether playwright should swallow SIGINT signals and kill the browser.'
	)
	handle_sigterm: bool = Field(
		default=False, description='Whether playwright should swallow SIGTERM signals and kill the browser.'
	)
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

	model_config = ConfigDict(extra='ignore', validate_assignment=False, revalidate_instances='always', populate_by_name=True)

	# storage_state is not supported in launch_persistent_context()
	storage_state: str | Path | dict[str, Any] | None = None
	# TODO: use StorageState type instead of dict[str, Any]

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

	model_config = ConfigDict(extra='ignore', validate_assignment=False, revalidate_instances='always')

	# Required parameter specific to launch_persistent_context, but can be None to use incognito temp dir
	user_data_dir: str | Path | None = CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR


class BrowserProfile(BrowserConnectArgs, BrowserLaunchPersistentContextArgs, BrowserLaunchArgs, BrowserNewContextArgs):
	"""
	A BrowserProfile is a static template collection of kwargs that can be passed to:
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

	# ... extends options defined in:
	# BrowserLaunchPersistentContextArgs, BrowserLaunchArgs, BrowserNewContextArgs, BrowserConnectArgs

	# Unique identifier for this browser profile
	id: str = Field(default_factory=uuid7str)
	# label: str = 'default'

	# custom options we provide that aren't native playwright kwargs
	stealth: bool = Field(default=False, description='Use stealth mode to avoid detection by anti-bot systems.')
	disable_security: bool = Field(default=False, description='Disable browser security features.')
	deterministic_rendering: bool = Field(default=False, description='Enable deterministic rendering flags.')
	allowed_domains: list[str] | None = Field(
		default=None,
		description='List of allowed domains for navigation e.g. ["*.google.com", "https://example.com", "chrome-extension://*"]',
	)
	keep_alive: bool | None = Field(default=None, description='Keep browser alive after agent run.')
	window_size: ViewportSize | None = Field(
		default=None,
		description='Browser window size to use when headless=False.',
	)
	window_height: int | None = Field(default=None, description='DEPRECATED, use window_size["height"] instead', exclude=True)
	window_width: int | None = Field(default=None, description='DEPRECATED, use window_size["width"] instead', exclude=True)
	window_position: ViewportSize | None = Field(
		default_factory=lambda: {'width': 0, 'height': 0},
		description='Window position to use for the browser x,y from the top left when headless=False.',
	)

	# --- Page load/wait timings ---
	default_navigation_timeout: float | None = Field(default=None, description='Default page navigation timeout.')
	default_timeout: float | None = Field(default=None, description='Default playwright call timeout.')
	minimum_wait_page_load_time: float = Field(default=0.25, description='Minimum time to wait before capturing page state.')
	wait_for_network_idle_page_load_time: float = Field(default=0.5, description='Time to wait for network idle.')
	maximum_wait_page_load_time: float = Field(default=5.0, description='Maximum time to wait for page load.')
	wait_between_actions: float = Field(default=0.5, description='Time to wait between actions.')

	# --- UI/viewport/DOM ---
	include_dynamic_attributes: bool = Field(default=True, description='Include dynamic attributes in selectors.')
	highlight_elements: bool = Field(default=True, description='Highlight interactive elements on the page.')
	viewport_expansion: int = Field(default=500, description='Viewport expansion in pixels for LLM context.')

	profile_directory: str = 'Default'  # e.g. 'Profile 1', 'Profile 2', 'Custom Profile', etc.

	# these can be found in BrowserLaunchArgs, BrowserLaunchPersistentContextArgs, BrowserNewContextArgs, BrowserConnectArgs:
	# save_recording_path: alias of record_video_dir
	# save_har_path: alias of record_har_path
	# trace_path: alias of traces_dir

	cookies_file: Path | None = Field(
		default=None, description='File to save cookies to. DEPRECATED, use `storage_state` instead.'
	)

	# TODO: finish implementing extension support in extensions.py
	# extension_ids_to_preinstall: list[str] = Field(
	# 	default_factory=list, description='List of Chrome extension IDs to preinstall.'
	# )
	# extensions_dir: Path = Field(
	# 	default_factory=lambda: Path('~/.config/browseruse/cache/extensions').expanduser(),
	# 	description='Directory containing .crx extension files.',
	# )

	def __repr__(self) -> str:
		short_dir = _log_pretty_path(self.user_data_dir) if self.user_data_dir else '<incognito>'
		return f'BrowserProfile#{self.id[-4:]}(user_data_dir= {short_dir}, headless={self.headless})'

	def __str__(self) -> str:
		return f'BrowserProfile#{self.id[-4:]}'

	@model_validator(mode='after')
	def copy_old_config_names_to_new(self) -> Self:
		"""Copy old config window_width & window_height to window_size."""
		if self.window_width or self.window_height:
			logger.warning(
				f'⚠️ BrowserProfile(window_width=..., window_height=...) are deprecated, use BrowserProfile(window_size={"width": 1280, "height": 1100}) instead.'
			)
			window_size = self.window_size or ViewportSize(width=0, height=0)
			window_size['width'] = window_size['width'] or self.window_width or 1280
			window_size['height'] = window_size['height'] or self.window_height or 1100
			self.window_size = window_size
		return self

	@model_validator(mode='after')
	def warn_storage_state_user_data_dir_conflict(self) -> Self:
		"""Warn when both storage_state and user_data_dir are set, as this can cause conflicts."""
		has_storage_state = self.storage_state is not None
		has_user_data_dir = self.user_data_dir is not None
		has_cookies_file = self.cookies_file is not None
		static_source = 'cookies_file' if has_cookies_file else 'storage_state' if has_storage_state else None

		if static_source and has_user_data_dir:
			logger.warning(
				f'⚠️ BrowserSession(...) was passed both {static_source} AND user_data_dir. {static_source}={self.storage_state or self.cookies_file} will forcibly overwrite '
				f'cookies/localStorage/sessionStorage in user_data_dir={self.user_data_dir}. '
				f'For multiple browsers in parallel, use only storage_state with user_data_dir=None, '
				f'or use a separate user_data_dir for each browser and set storage_state=None.'
			)
		return self

	@model_validator(mode='after')
	def warn_user_data_dir_non_default_version(self) -> Self:
		"""
		If user is using default profile dir with a non-default channel, force-change it
		to avoid corrupting the default data dir created with a different channel.
		"""

		is_not_using_default_chromium = self.executable_path or self.channel not in (BROWSERUSE_DEFAULT_CHANNEL, None)
		if self.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR and is_not_using_default_chromium:
			alternate_name = (
				Path(self.executable_path).name.lower().replace(' ', '-')
				if self.executable_path
				else self.channel.name.lower()
				if self.channel
				else 'None'
			)
			logger.warning(
				f'⚠️ {self} Changing user_data_dir= {_log_pretty_path(self.user_data_dir)} ➡️ .../default-{alternate_name} to avoid {alternate_name.upper()} corruping default profile created by {BROWSERUSE_DEFAULT_CHANNEL.name}'
			)
			self.user_data_dir = CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / f'default-{alternate_name}'
		return self

	@model_validator(mode='after')
	def warn_deterministic_rendering_weirdness(self) -> Self:
		if self.deterministic_rendering:
			logger.warning(
				'⚠️ BrowserSession(deterministic_rendering=True) is NOT RECOMMENDED. It breaks many sites and increases chances of getting blocked by anti-bot systems. '
				'It hardcodes the JS random seed and forces browsers across Linux/Mac/Windows to use the same font rendering engine so that identical screenshots can be generated.'
			)
		return self

	def get_args(self) -> list[str]:
		"""Get the list of all Chrome CLI launch args for this profile (compiled from defaults, user-provided, and system-specific)."""

		if isinstance(self.ignore_default_args, list):
			default_args = set(CHROME_DEFAULT_ARGS) - set(self.ignore_default_args)
		elif self.ignore_default_args is True:
			default_args = []
		elif not self.ignore_default_args:
			default_args = CHROME_DEFAULT_ARGS

		# Capture args before conversion for logging
		pre_conversion_args = [
			*default_args,
			*self.args,
			f'--profile-directory={self.profile_directory}',
			*(CHROME_DOCKER_ARGS if CONFIG.IN_DOCKER else []),
			*(CHROME_HEADLESS_ARGS if self.headless else []),
			*(CHROME_DISABLE_SECURITY_ARGS if self.disable_security else []),
			*(CHROME_DETERMINISTIC_RENDERING_ARGS if self.deterministic_rendering else []),
			*(
				[f'--window-size={self.window_size["width"]},{self.window_size["height"]}']
				if self.window_size
				else (['--start-maximized'] if not self.headless else [])
			),
			*(
				[f'--window-position={self.window_position["width"]},{self.window_position["height"]}']
				if self.window_position
				else []
			),
		]

		# convert to dict and back to dedupe and merge duplicate args
		final_args_list = BrowserLaunchArgs.args_as_list(BrowserLaunchArgs.args_as_dict(pre_conversion_args))
		return final_args_list

	def kwargs_for_launch_persistent_context(self) -> BrowserLaunchPersistentContextArgs:
		"""Return the kwargs for BrowserType.launch()."""
		return BrowserLaunchPersistentContextArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	def kwargs_for_new_context(self) -> BrowserNewContextArgs:
		"""Return the kwargs for BrowserContext.new_context()."""
		return BrowserNewContextArgs(**self.model_dump(exclude={'args'}))

	def kwargs_for_connect(self) -> BrowserConnectArgs:
		"""Return the kwargs for BrowserType.connect()."""
		return BrowserConnectArgs(**self.model_dump(exclude={'args'}))

	def kwargs_for_launch(self) -> BrowserLaunchArgs:
		"""Return the kwargs for BrowserType.connect_over_cdp()."""
		return BrowserLaunchArgs(**self.model_dump(exclude={'args'}), args=self.get_args())

	# def preinstall_extensions(self) -> None:
	# 	"""Preinstall the extensions."""

	#     # create the local unpacked extensions dir
	# 	extensions_dir = self.user_data_dir / 'Extensions'
	# 	extensions_dir.mkdir(parents=True, exist_ok=True)

	#     # download from the chrome web store using the chrome web store api
	# 	for extension_id in self.extension_ids_to_preinstall:
	# 		extension_path = extensions_dir / f'{extension_id}.crx'
	# 		if extension_path.exists():
	# 			logger.warning(f'⚠️ Extension {extension_id} is already installed, skipping preinstall.')
	# 		else:
	# 			logger.info(f'🔍 Preinstalling extension {extension_id}...')
	# 			# TODO: copy this from ArchiveBox implementation

	@observe_debug(name='detect_display_configuration')
	def detect_display_configuration(self) -> None:
		"""
		Detect the system display size and initialize the display-related config defaults:
		        screen, window_size, window_position, viewport, no_viewport, device_scale_factor
		"""

		display_size = get_display_size()
		has_screen_available = bool(display_size)
		self.screen = self.screen or display_size or ViewportSize(width=1280, height=1100)

		# if no headless preference specified, prefer headful if there is a display available
		if self.headless is None:
			self.headless = not has_screen_available

		# set up window size and position if headful
		if self.headless:
			# headless mode: no window available, use viewport instead to constrain content size
			self.viewport = self.viewport or self.window_size or self.screen
			self.window_position = None  # no windows to position in headless mode
			self.window_size = None
			self.no_viewport = False  # viewport is always enabled in headless mode
		else:
			# headful mode: use window, disable viewport by default, content fits to size of window
			self.window_size = self.window_size or self.screen
			self.no_viewport = True if self.no_viewport is None else self.no_viewport
			self.viewport = None if self.no_viewport else self.viewport

		# automatically setup viewport if any config requires it
		use_viewport = self.headless or self.viewport or self.device_scale_factor
		self.no_viewport = not use_viewport if self.no_viewport is None else self.no_viewport
		use_viewport = not self.no_viewport

		if use_viewport:
			# if we are using viewport, make device_scale_factor and screen are set to real values to avoid easy fingerprinting
			self.viewport = self.viewport or self.screen
			self.device_scale_factor = self.device_scale_factor or 1.0
			assert self.viewport is not None
			assert self.no_viewport is False
		else:
			# device_scale_factor and screen are not supported non-viewport mode, the system monitor determines these
			self.viewport = None
			self.device_scale_factor = None  # only supported in viewport mode
			self.screen = None  # only supported in viewport mode
			assert self.viewport is None
			assert self.no_viewport is True

		assert not (self.headless and self.no_viewport), 'headless=True and no_viewport=True cannot both be set at the same time'
