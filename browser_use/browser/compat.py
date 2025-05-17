DEPRECATION_MESSAGE = """
↗️ We have moved to a new, simplified BrowserProfile and BrowserSession API. Old code that uses browser_use.browser.{} must be updated.

👍 Thank you for your patience as we work to simplify our API! Migration is easy:

	from browser_use.browser import BrowserProfile, BrowserSession
	
	# the new 👤 BrowserProfile(...) and 🚀 BrowserSession(...) support 100% standard 🎭 playwright options:
	#    
 
	# 1. 👤 create a BrowserProfile() object and put *all* your browser-related config into it
	browser_profile = BrowserProfile(
		# 🎭 all the standard Playwright launch & context options can go here:
		executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		user_data_dir='/path/to/user_data_dir',
		headless=False,
		args=['--start-maximized'],
		ignore_default_args=['--enable-automation'],
		viewport={'width': 1920, 'height': 1080},
		has_touch=False,
		user_agent='...',
		# ... see more: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
		
		# ♾️ Browser-Use's browser options can also go here:
		#    Browser(...)				➡️ move here	⬇️  ...
		# 	 BrowserConfig(...)			➡️ move here	⬇️  ...
		# 	 BrowserContextConfig(...)	➡️ move here	⬇️  ...
		highlight_elements=True,
		allowed_domains=['example.com', '*.google.com'],
		disable_security=False,
		keep_alive=True,
		window_size={'width': 1920, 'height': 1080},
		# ... see more: https://docs.browser-use.com/customize/browser-settings#context-configuration
	)

	# 2. 🚀 create a BrowserSession() to connect to a browser
	browser_session = BrowserSession(
		# A. Local: pass a 👤 BrowserProfile to launch a local browser with that config
		browser_profile=browser_profile,
		# ... extra kwargs can be passed to override browser_profile settings on a per-session basis, e.g.:
		# executable_path='/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
		# user_data_dir='~/Desktop/new-test-profile',
		# headless=True,
		
		# OR B. Remote: pass 🔗 cdp_url or wss_URL to use an existing remote browser
		# cdp_url='http://localhost:9222',
		# wss_url='ws://some-playwright-node-server:9292',
		
		# OR C. Existing: pass existing playwright/patchright browser objects
		# browser=playwright_browser_obj,
		# browser_context=playwright_browser_context_obj,
	)
	agent = Agent(browser_session=browser_session, ...)
	...
"""


class DeprecatedClass:
	def __init__(self, *_args, **_kwargs):
		print(DEPRECATION_MESSAGE.format(type(self).__name__))
		raise NotImplementedError(
			'The Browser, BrowserConfig, BrowserContext, BrowserContextConfig models have been moved to a simplified new design => 1 BrowserProfile + 1 BrowserSession.'
		)


class BrowserConfig(DeprecatedClass):
	pass


class BrowserContextConfig(DeprecatedClass):
	pass


class Browser(DeprecatedClass):
	pass


class BrowserContext(DeprecatedClass):
	pass
