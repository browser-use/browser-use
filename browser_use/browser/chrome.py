CHROME_EXTENSIONS = {}  # coming in a separate PR
CHROME_EXTENSIONS_PATH = 'chrome_extensions'
CHROME_PROFILE_PATH = 'chrome_profile'
CHROME_PROFILE_USER = 'Default'
CHROME_DEBUG_PORT = 9222
CHROME_DISABLED_COMPONENTS = [
	'Translate',
	'AcceptCHFrame',
	'OptimizationHints',
	'ProcessPerSiteUpToMainFrameThreshold',
	'InterestFeedContentSuggestions',
	'CalculateNativeWinOcclusion',
	'BackForwardCache',
	'HeavyAdPrivacyMitigations',
	'LazyFrameLoading',
	'ImprovedCookieControls',
	'PrivacySandboxSettings4',
	'AutofillServerCommunication',
	'CertificateTransparencyComponentUpdater',
	'DestroyProfileOnBrowserClose',
	'CrashReporting',
	'OverscrollHistoryNavigation',
	'InfiniteSessionRestore',
	#'LockProfileCookieDatabase',  # disabling allows multiple chrome instances to concurrently modify profile, but might make chrome much slower https://github.com/yt-dlp/yt-dlp/issues/7271  https://issues.chromium.org/issues/40901624
]  # it's always best to give each chrome instance its own exclusive copy of the user profile


CHROME_HEADLESS_ARGS = [
	'--headless=new',
	# '--test-type',
	# '--test-type=gpu',  # https://github.com/puppeteer/puppeteer/issues/10516
	# '--enable-automation',                            # <- DONT USE THIS, it makes you easily detectable / blocked by cloudflare
]

CHROME_DOCKER_ARGS = [
	# Docker-specific options
	# https://github.com/GoogleChrome/lighthouse-ci/tree/main/docs/recipes/docker-client#--no-sandbox-issues-explained
	'--no-sandbox',  # rely on docker sandboxing in docker, otherwise we need cap_add: SYS_ADM to use host sandboxing
	'--disable-gpu-sandbox',
	'--disable-setuid-sandbox',
	'--disable-dev-shm-usage',  # docker 75mb default shm size is not big enough, disabling just uses /tmp instead
	'--no-xshm',
	# dont try to disable (or install) dbus in docker, its not needed, chrome can work without dbus despite the errors
]

CHROME_DISABLE_SECURITY_ARGS = [
	# DANGER: JS isolation security features (to allow easier tampering with pages during automation)
	# chrome://net-internals
	'--disable-web-security',  # <- WARNING, breaks some sites that expect/enforce strict CORS headers (try webflow.com)
	'--disable-site-isolation-trials',
	'--disable-features=IsolateOrigins,site-per-process',
	# '--allow-file-access-from-files',                     # <- WARNING, dangerous, allows JS to read filesystem using file:// URLs
	# DANGER: Disable HTTPS verification
	'--allow-running-insecure-content',  # Breaks CORS/CSRF/HSTS etc., useful sometimes but very easy to detect
	'--ignore-certificate-errors',
	'--ignore-ssl-errors',
	'--ignore-certificate-errors-spki-list',
	'--allow-insecure-localhost',
]

# flags to make chrome behave more deterministically across different OS's
CHROME_DETERMINISTIC_RENDERING_ARGS = [
	# '--deterministic-mode',
	# '--js-flags=--random-seed=1157259159',  # make all JS random numbers deterministic by providing a seed
	# '--force-device-scale-factor=1',
	'--hide-scrollbars',  # hide scrollbars because otherwise they show up in screenshots
	# GPU, canvas, text, and pdf rendering config
	# chrome://gpu
	# '--enable-webgl',  # enable web-gl graphics support
	# '--font-render-hinting=none',  # make rendering more deterministic by ignoring OS font hints, may also need css override, try:    * {text-rendering: geometricprecision !important; -webkit-font-smoothing: antialiased;}
	# '--force-color-profile=srgb',  # make rendering more deterministic by using consistent color profile, if browser looks weird, try: generic-rgb
	# '--disable-partial-raster',  # make rendering more deterministic (TODO: verify if still needed)
	# '--disable-skia-runtime-opts',  # make rendering more deterministic by avoiding Skia hot path runtime optimizations
	# '--disable-2d-canvas-clip-aa',  # make rendering more deterministic by disabling antialiasing on 2d canvas clips
	# '--disable-gpu',                                  # falls back to more consistent software renderer across all OS's, especially helps linux text rendering look less weird
	# // '--use-gl=swiftshader',                        <- DO NOT USE, breaks M1 ARM64. it makes rendering more deterministic by using simpler CPU renderer instead of OS GPU renderer  bug: https://groups.google.com/a/chromium.org/g/chromium-dev/c/8eR2GctzGuw
	# // '--disable-software-rasterizer',               <- DO NOT USE, harmless, used in tandem with --disable-gpu
	# // '--run-all-compositor-stages-before-draw',     <- DO NOT USE, makes headful chrome hang on startup (tested v121 Google Chrome.app on macOS)
	# // '--disable-gl-drawing-for-tests',              <- DO NOT USE, disables gl output (makes tests run faster if you dont care about canvas)
	# // '--blink-settings=imagesEnabled=false',        <- DO NOT USE, disables images entirely (only sometimes useful to speed up loading)
	# Process management & performance tuning
	# chrome://process-internals
	# '--disable-lazy-loading',  # make rendering more deterministic by loading all content up-front instead of on-focus
	# '--disable-renderer-backgrounding',  # dont throttle tab rendering based on focus/visibility
	# '--disable-background-networking',  # dont throttle tab networking based on focus/visibility
	# '--disable-background-timer-throttling',  # dont throttle tab timers based on focus/visibility
	# '--disable-backgrounding-occluded-windows',  # dont throttle tab window based on focus/visibility
	# '--disable-ipc-flooding-protection',  # dont throttle ipc traffic or accessing big request/response/buffer/etc. objects will fail
	# '--disable-extensions-http-throttling',  # dont throttle http traffic based on runtime heuristics
	# '--disable-field-trial-config',  # disable shared field trial state between browser processes
	# '--disable-back-forward-cache',  # disable browsing navigation cache
]


CHROME_ARGS = [
	# Profile data dir setup
	# chrome://profile-internals
	# f'--user-data-dir={CHROME_PROFILE_PATH}',     # managed by playwright arg instead
	# f'--profile-directory={CHROME_PROFILE_USER}',
	# '--password-store=basic',  # use mock keychain instead of OS-provided keychain (we manage auth.json instead)
	# '--use-mock-keychain',
	# '--disable-cookie-encryption',  # we need to be able to write unencrypted cookies to save/load auth.json
	'--disable-sync',  # don't try to use Google account sync features while automation is active
	# Extensions
	# chrome://inspect/#extensions
	# f'--load-extension={CHROME_EXTENSIONS.map(({unpacked_path}) => unpacked_path).join(',')}',  # not needed when using existing profile that already has extensions installed
	# f'--allowlisted-extension-id={",".join(CHROME_EXTENSIONS.keys())}',
	'--allow-legacy-extension-manifests',
	'--allow-pre-commit-input',  # allow JS mutations before page rendering is complete
	# '--disable-blink-features=AutomationControlled',  # hide the signatures that announce browser is being remote-controlled
	# f'--proxy-server=https://43.159.28.126:2334:u7ce652b7568805c4-zone-custom-region-us-session-szGWq3FRU-sessTime-60:u7ce652b7568805c4',      # send all network traffic through a proxy https://2captcha.com/proxy
	# f'--proxy-bypass-list=127.0.0.1',
	# Browser window and viewport setup
	# chrome://version
	# f'--user-agent="{DEFAULT_USER_AGENT}"',
	# f'--window-size={DEFAULT_VIEWPORT.width},{DEFAULT_VIEWPORT.height}',
	# '--window-position=0,0',
	# '--start-maximized',
	'--install-autogenerated-theme=0,0,0',  # black border makes it easier to see which chrome window is browser-use's
	#'--virtual-time-budget=60000',  # fast-forward all animations & timers by 60s, dont use this it's unfortunately buggy and breaks screenshot and PDF capture sometimes
	#'--autoplay-policy=no-user-gesture-required',  # auto-start videos so they trigger network requests + show up in outputs
	#'--disable-gesture-requirement-for-media-playback',
	#'--lang=en-US,en;q=0.9',
	# IO: stdin/stdout, debug port config
	# chrome://inspect
	'--log-level=2',  # 1=DEBUG 2=WARNING 3=ERROR
	'--enable-logging=stderr',
	# '--remote-debugging-address=127.0.0.1',         <- never expose to non-localhost, would allow attacker to drive your browser from any machine
	# '--enable-experimental-extension-apis',  # add support for tab groups
	'--disable-focus-on-load',  # prevent browser from hijacking focus
	'--disable-window-activation',
	# '--in-process-gpu',                            <- DONT USE THIS, makes headful startup time ~5-10s slower (tested v121 Google Chrome.app on macOS)
	# '--disable-component-extensions-with-background-pages',  # TODO: check this, disables chrome components that only run in background with no visible UI (could lower startup time)
	# uncomment to disable hardware camera/mic/speaker access + present fake devices to websites
	# (faster to disable, but disabling breaks recording browser audio in puppeteer-stream screenrecordings)
	# '--use-fake-device-for-media-stream',
	# '--use-fake-ui-for-media-stream',
	# '--disable-features=GlobalMediaControls,MediaRouter,DialMediaRouteProvider',
	# Output format options (PDF, screenshot, etc.)
	'--export-tagged-pdf',  # include table on contents and tags in printed PDFs
	'--generate-pdf-document-outline',
	# Suppress first-run features, popups, hints, updates, etc.
	# chrome://system
	'--no-pings',
	'--no-first-run',
	'--no-default-browser-check',
	'--no-startup-window',
	'--ash-no-nudges',
	'--disable-infobars',
	'--disable-search-engine-choice-screen',
	'--disable-session-crashed-bubble',
	'--simulate-outdated-no-au="Tue, 31 Dec 2099 23:59:59 GMT"',  # disable browser self-update while automation is active
	'--hide-crash-restore-bubble',
	'--suppress-message-center-popups',
	'--disable-client-side-phishing-detection',
	'--disable-domain-reliability',
	'--disable-datasaver-prompt',
	'--disable-hang-monitor',
	'--disable-session-crashed-bubble',
	'--disable-speech-synthesis-api',
	'--disable-speech-api',
	'--disable-print-preview',
	'--safebrowsing-disable-auto-update',
	# '--deny-permission-prompts',
	'--disable-external-intent-requests',
	'--disable-notifications',
	'--disable-desktop-notifications',
	'--noerrdialogs',
	'--disable-prompt-on-repost',
	'--silent-debugger-extension-api',
	'--block-new-web-contents',
	'--metrics-recording-only',
	'--disable-breakpad',
	# other feature flags
	# chrome://flags        chrome://components
	# f'--disable-features={",".join(CHROME_DISABLED_COMPONENTS)}',
	# '--enable-features=NetworkService',
]
