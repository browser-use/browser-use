# pyright: reportMissingImports=false
# We do this because we need to install the other browser packages but dont want them in our main package dependencies

import asyncio
import json
import logging
import os
from pathlib import Path

import requests

from browser_use import BrowserProfile, BrowserSession
from eval.task_types import Task

logger = logging.getLogger(__name__)

# Check for Anchor Browser API key
ANCHOR_BROWSER_API_KEY = os.getenv('ANCHOR_BROWSER_API_KEY')
if ANCHOR_BROWSER_API_KEY:
	logger.info('ANCHOR_BROWSER_API_KEY is set. Tasks can use Anchor Browser.')
else:
	logger.warning('ANCHOR_BROWSER_API_KEY is not set. Anchor Browser will not be available.')

# Check for Brightdata CDP URL
BRIGHTDATA_CDP_URL = os.getenv('BRIGHTDATA_CDP_URL')
if BRIGHTDATA_CDP_URL:
	logger.info('BRIGHTDATA_CDP_URL is set. Tasks can use Brightdata browser.')
else:
	logger.warning('BRIGHTDATA_CDP_URL is not set. Brightdata browser will not be available.')

# Check for Browserbase API key
BROWSERBASE_API_KEY = os.getenv('BROWSERBASE_API_KEY')
BROWSERBASE_PROJECT_ID = os.getenv('BROWSERBASE_PROJECT_ID')
if BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID:
	logger.info('BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID are set. Tasks can use Browserbase.')
else:
	logger.warning('BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID are not set. Browserbase will not be available.')

# Check for Hyperbrowser API key
HYPERBROWSER_API_KEY = os.getenv('HYPERBROWSER_API_KEY')
if HYPERBROWSER_API_KEY:
	logger.info('HYPERBROWSER_API_KEY is set. Tasks can use Hyperbrowser.')
else:
	logger.warning('HYPERBROWSER_API_KEY is not set. Hyperbrowser will not be available.')


def create_anchor_browser_session(headless: bool = False) -> str:
	"""Create an Anchor Browser session and return CDP URL"""
	if not ANCHOR_BROWSER_API_KEY:
		raise ValueError('ANCHOR_BROWSER_API_KEY must be set')

	browser_configuration = {
		'session': {'proxy': {'type': 'anchor_mobile', 'active': True, 'country_code': 'us'}},
		'browser': {
			'adblock': {'active': True},
			'captcha_solver': {'active': True},
			'headless': {'active': headless},
			'extra_stealth': {'active': True},
		},
	}

	try:
		response = requests.post(
			'https://api.anchorbrowser.io/v1/sessions',
			headers={
				'anchor-api-key': ANCHOR_BROWSER_API_KEY,
				'Content-Type': 'application/json',
			},
			json=browser_configuration,
			timeout=10,
		)
		response.raise_for_status()
		session_data = response.json()['data']
		session_id = session_data['id']

		return f'wss://connect.anchorbrowser.io?apiKey={ANCHOR_BROWSER_API_KEY}&sessionId={session_id}'

	except requests.RequestException as e:
		logger.error(f'Failed to create Anchor Browser session: {type(e).__name__}: {e}')
		raise
	except KeyError as e:
		logger.error(f'Unexpected response format from Anchor Browser API: {e}')
		raise


def create_browserbase_session() -> str:
	"""Create a Browserbase session and return CDP URL"""
	if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT_ID:
		raise ValueError('BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID must be set')

	try:
		from browserbase import Browserbase
	except ImportError:
		raise ImportError(
			'browserbase package is required for Browserbase functionality. Install it with: pip install browserbase'
		)

	try:
		bb = Browserbase(api_key=BROWSERBASE_API_KEY)
		session = bb.sessions.create(
			project_id=BROWSERBASE_PROJECT_ID,
			proxies=True,
		)

		return session.connect_url

	except Exception as e:
		logger.error(f'Failed to create Browserbase session: {type(e).__name__}: {e}')
		raise


async def create_hyperbrowser_session() -> str:
	"""Create a Hyperbrowser session and return WebSocket endpoint"""
	if not HYPERBROWSER_API_KEY:
		raise ValueError('HYPERBROWSER_API_KEY must be set')

	try:
		from hyperbrowser import AsyncHyperbrowser
		from hyperbrowser.models import CreateSessionParams
	except ImportError:
		raise ImportError(
			'hyperbrowser package is required for Hyperbrowser functionality. Install it with: pip install hyperbrowser'
		)

	try:
		client = AsyncHyperbrowser(api_key=HYPERBROWSER_API_KEY)

		session = await client.sessions.create(
			params=CreateSessionParams(
				use_stealth=True,
			)
		)

		await client.close()

		return session.ws_endpoint or ''

	except Exception as e:
		logger.error(f'Failed to create Hyperbrowser session: {type(e).__name__}: {e}')
		raise


async def setup_browser_session(
	task: Task,
	headless: bool,
	highlight_elements: bool = True,
	browser: str = 'local',
	default_navigation_timeout: int | None = None,
	default_timeout: int | None = None,
	minimum_wait_page_load_time: float | None = None,
	wait_for_network_idle_page_load_time: float | None = None,
	maximum_wait_page_load_time: float | None = None,
	wait_between_actions: float | None = None,
	stealth: bool = False,
) -> BrowserSession:
	"""Setup browser session for the task"""

	# Validate browser option
	valid_browsers = ['local', 'anchor-browser', 'brightdata', 'browserbase', 'hyperbrowser', 'browser-use']
	if browser not in valid_browsers:
		logger.warning(f'Browser setup: Invalid browser option "{browser}". Falling back to local browser.')
		browser = 'local'

	cdp_url = None

	if browser == 'anchor-browser':
		if ANCHOR_BROWSER_API_KEY:
			try:
				logger.debug(f'Browser setup: Creating Anchor Browser session for task {task.task_id}')
				cdp_url = await asyncio.to_thread(create_anchor_browser_session, headless)
			except Exception as e:
				logger.error(
					f'Browser setup: Failed to create Anchor Browser session for task {task.task_id}: {type(e).__name__}: {e}'
				)
				logger.info(f'Browser setup: Falling back to local browser for task {task.task_id}')
				cdp_url = None
		else:
			logger.warning(
				f'Browser setup: Anchor Browser requested but ANCHOR_BROWSER_API_KEY not set. Using local browser for task {task.task_id}'
			)
	elif browser == 'brightdata':
		if BRIGHTDATA_CDP_URL:
			logger.debug(f'Browser setup: Using Brightdata CDP URL for task {task.task_id}')
			cdp_url = BRIGHTDATA_CDP_URL
		else:
			logger.warning(
				f'Browser setup: Brightdata requested but BRIGHTDATA_CDP_URL not set. Using local browser for task {task.task_id}'
			)
	elif browser == 'browserbase':
		if BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID:
			try:
				logger.debug(f'Browser setup: Creating Browserbase session for task {task.task_id}')
				cdp_url = await asyncio.to_thread(create_browserbase_session)
			except Exception as e:
				logger.error(
					f'Browser setup: Failed to create Browserbase session for task {task.task_id}: {type(e).__name__}: {e}'
				)
				logger.info(f'Browser setup: Falling back to local browser for task {task.task_id}')
				cdp_url = None
		else:
			logger.warning(
				f'Browser setup: Browserbase requested but BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set. Using local browser for task {task.task_id}'
			)
	elif browser == 'hyperbrowser':
		if HYPERBROWSER_API_KEY:
			try:
				logger.debug(f'Browser setup: Creating Hyperbrowser session for task {task.task_id}')
				cdp_url = await create_hyperbrowser_session()
			except Exception as e:
				logger.error(
					f'Browser setup: Failed to create Hyperbrowser session for task {task.task_id}: {type(e).__name__}: {e}'
				)
				logger.info(f'Browser setup: Falling back to local browser for task {task.task_id}')
				cdp_url = None
		else:
			logger.warning(
				f'Browser setup: Hyperbrowser requested but HYPERBROWSER_API_KEY not set. Using local browser for task {task.task_id}'
			)
	elif browser == 'browser-use':
		logger.warning(f'Browser setup: Browser-use not implemented yet. Falling back to local browser for task {task.task_id}')

	profile_kwargs = {
		'user_data_dir': None,  # Incognito mode - no persistent state
		'headless': headless,
		'chromium_sandbox': False,  # running in docker
		'highlight_elements': highlight_elements,  # Control element highlighting (passed to profile)
		'keep_alive': True,
		'stealth': stealth,
		# higher timeouts = higher success rates on long tail of slow sites or if on a slow CI server
		# ignore_https_errors=True,  # some eval tasks have http:// or broken https sites in them
	}

	# Add timeout parameters if provided
	if default_navigation_timeout is not None:
		profile_kwargs['default_navigation_timeout'] = default_navigation_timeout
	if default_timeout is not None:
		profile_kwargs['default_timeout'] = default_timeout
	if minimum_wait_page_load_time is not None:
		profile_kwargs['minimum_wait_page_load_time'] = minimum_wait_page_load_time
	if wait_for_network_idle_page_load_time is not None:
		profile_kwargs['wait_for_network_idle_page_load_time'] = wait_for_network_idle_page_load_time
	if maximum_wait_page_load_time is not None:
		profile_kwargs['maximum_wait_page_load_time'] = maximum_wait_page_load_time
	if wait_between_actions is not None:
		profile_kwargs['wait_between_actions'] = wait_between_actions

	if hasattr(task, 'login_cookie') and task.login_cookie:
		# For login tasks, configure storage_state to save cookies to JSON file
		# Don't set user_data_dir=None for login tasks to avoid conflict
		task_folder = Path(f'saved_trajectories/{task.task_id}')
		task_folder.mkdir(parents=True, exist_ok=True)

		storage_state_path = task_folder / 'storage_state.json'
		# Create empty storage state file if it doesn't exist to avoid FileNotFoundError
		if not storage_state_path.exists():
			storage_state_path.write_text(json.dumps({'cookies': [], 'origins': []}))

		profile_kwargs['storage_state'] = str(storage_state_path)
		# Remove user_data_dir=None for login tasks to avoid conflict with storage_state
		profile_kwargs.pop('user_data_dir', None)

		downloads_dir_path = task_folder / 'downloads'
		downloads_dir_path.mkdir(parents=True, exist_ok=True)
		profile_kwargs['downloads_path'] = str(downloads_dir_path)

		logger.debug(f'Login task {task.task_id}: Configured to save cookies to {storage_state_path}')

	profile = BrowserProfile(**profile_kwargs)

	if cdp_url:
		logger.debug(f'Browser setup: Using CDP Browser for task {task.task_id}')
		browser_session = BrowserSession(browser_profile=profile, cdp_url=cdp_url)
	else:
		# Use local browser
		logger.debug(f'Browser setup: Initializing BrowserSession for task {task.task_id}')
		browser_session = BrowserSession(browser_profile=profile)

	# Start browser session
	await browser_session.start()
	logger.debug(f'Browser setup: Browser session started for task {task.task_id}')

	# Navigate to task starting url if provided
	# if task.website:
	# logger.debug(f'Browser setup: Navigating to {task.website} for task {task.task_id}')
	# await browser_session.navigate(task.website)

	logger.debug(f'Browser setup: Setup completed for task {task.task_id}')
	return browser_session
