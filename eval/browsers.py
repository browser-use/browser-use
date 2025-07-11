# pyright: reportMissingImports=false
# We do this because we need to install the other browser packages but dont want them in our main package dependencies

import asyncio
import json
import logging
import os
import random
import string
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

# Check for Unikraft Cloud API key
UKC_TOKEN = os.getenv('UKC_TOKEN')
UKC_METRO = os.getenv('UKC_METRO')
if UKC_TOKEN and UKC_METRO:
	logger.info('UKC_TOKEN and UKC_METRO are set. Tasks can use Unikraft browser.')
else:
	logger.warning('UKC_TOKEN or UKC_METRO are not set. Unikraft browser will not be available.')


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


async def create_unikraft_session(headless: bool = False) -> str:
	"""Create a Unikraft Cloud instance and return CDP URL"""
	if not UKC_TOKEN:
		raise ValueError('UKC_TOKEN must be set')

	if not UKC_METRO:
		raise ValueError('UKC_METRO must be set')

	# Load configuration from environment or defaults
	registry_user = os.getenv('REGISTRY_USER', 'browseruse')
	instance_name = os.getenv('APP_NAME', 'cdp') + '-' + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
	img_name = os.getenv('IMG_NAME', 'cdp')
	img_tag = os.getenv('IMG_TAG', 'latest')
	memory = os.getenv('MEMORY', '4Gi')

	# Convert memory to MB
	memory_mb = 8192  # Default 8GB
	if memory.endswith('Gi'):
		memory_mb = int(memory[:-2]) * 1024
	elif memory.endswith('Mi'):
		memory_mb = int(memory[:-2])

	# Prepare API request
	api_url = f'{UKC_METRO}/instances'
	headers = {'Authorization': f'Bearer {UKC_TOKEN}', 'Content-Type': 'application/json'}

	env_vars = {
		'UKC_METRO': UKC_METRO,
		'UKC_TOKEN': UKC_TOKEN,
		'UKC_INSTANCE_NAME': instance_name,
	}

	body = {
		'name': instance_name,
		'image': f'{registry_user}/{img_name}:{img_tag}',
		'memory_mb': memory_mb,
		'env': env_vars,
		'service_group': {
			'services': [{'port': 443, 'destination_port': 8080, 'handlers': ['tls', 'http']}],
			'domains': [{'name': instance_name}],
		},
		'autostart': True,
		'wait_timeout_ms': 10000,
		'scale_to_zero': {'policy': 'idle', 'cooldown_time_ms': 5000, 'stateful': True},
	}

	import aiohttp

	try:
		# Create instance
		timeout = aiohttp.ClientTimeout(total=30)
		async with aiohttp.ClientSession(timeout=timeout) as session:
			async with session.post(api_url, headers=headers, json=body) as response:
				response.raise_for_status()
				result = await response.json()

		if result.get('status') != 'success':
			raise ValueError(f'API returned error: {result}')

		instance_data = result['data']['instances'][0]
		instance_uuid = instance_data.get('uuid')
		service_group = instance_data.get('service_group', {})
		domains = service_group.get('domains', [])

		if not domains:
			raise ValueError('No domain returned for instance')

		fqdn = domains[0].get('fqdn')
		if not fqdn:
			raise ValueError('No FQDN returned for instance')

		# Wait for instance to be ready
		await _wait_for_unikraft_instance_ready(instance_uuid)

		# Wait for application to be ready
		instance_url = f'https://{fqdn}'
		await _wait_for_unikraft_app_ready(instance_url)

		# Return CDP WebSocket URL
		cdp_url = f'{instance_url}/ws/?headless={str(headless).lower()}&ephemeral=true'
		return cdp_url

	except Exception as e:
		logger.error(f'Failed to create Unikraft instance: {type(e).__name__}: {e}')
		raise


async def _wait_for_unikraft_instance_ready(instance_uuid: str, max_wait: int = 60) -> bool:
	"""Wait for Unikraft instance to be in running state"""
	import aiohttp

	api_url = f'{UKC_METRO}/instances/{instance_uuid}'
	headers = {'Authorization': f'Bearer {UKC_TOKEN}'}
	timeout = aiohttp.ClientTimeout(total=10)

	start_time = asyncio.get_event_loop().time()
	async with aiohttp.ClientSession(timeout=timeout) as session:
		while (asyncio.get_event_loop().time() - start_time) < max_wait:
			try:
				async with session.get(api_url, headers=headers) as response:
					if response.status == 200:
						result = await response.json()
						if result.get('status') == 'success':
							instance_data = result['data']['instances'][0]
							state = instance_data.get('state')

							if state == 'running':
								return True
							elif state in ['error', 'stopped']:
								raise ValueError(f'Instance entered {state} state')

				await asyncio.sleep(1)
			except Exception as e:
				if (asyncio.get_event_loop().time() - start_time) >= max_wait:
					raise ValueError(f'Instance failed to become ready: {e}')
				await asyncio.sleep(2)

	raise ValueError('Instance failed to become ready within timeout')


async def _wait_for_unikraft_app_ready(instance_url: str, max_wait: int = 60) -> bool:
	"""Wait for the Unikraft application to be ready by checking health endpoint"""
	import aiohttp

	start_time = asyncio.get_event_loop().time()
	timeout = aiohttp.ClientTimeout(total=5)

	async with aiohttp.ClientSession(timeout=timeout) as session:
		while (asyncio.get_event_loop().time() - start_time) < max_wait:
			try:
				async with session.get(f'{instance_url}/health') as resp:
					if resp.status == 200:
						data = await resp.json()
						if data.get('status') == 'healthy':
							return True
			except Exception:
				pass

			await asyncio.sleep(2)

	raise ValueError('Application failed to become ready within timeout')


async def _retry_browser_creation(browser_func, max_retries: int = 3, *args, **kwargs) -> str:
	"""Retry browser creation function with exponential backoff"""
	for attempt in range(max_retries):
		try:
			if asyncio.iscoroutinefunction(browser_func):
				return await browser_func(*args, **kwargs)
			else:
				return await asyncio.to_thread(browser_func, *args, **kwargs)
		except Exception as e:
			if attempt == max_retries - 1:  # Last attempt
				raise RuntimeError(f'Failed to create browser session after {max_retries} attempts: {type(e).__name__}: {e}')

			wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
			logger.warning(f'Browser creation attempt {attempt + 1} failed: {type(e).__name__}: {e}. Retrying in {wait_time}s...')
			await asyncio.sleep(wait_time)

	raise RuntimeError(f'Failed to create browser session after {max_retries} attempts')


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
	valid_browsers = ['local', 'anchor-browser', 'brightdata', 'browserbase', 'hyperbrowser', 'unikraft', 'browser-use']
	if browser not in valid_browsers:
		raise ValueError(f'Browser setup: Invalid browser option "{browser}". Valid options are: {valid_browsers}')

	cdp_url = None

	if browser == 'anchor-browser':
		if not ANCHOR_BROWSER_API_KEY:
			raise ValueError(
				f'Browser setup: Anchor Browser requested but ANCHOR_BROWSER_API_KEY not set for task {task.task_id}'
			)

		logger.debug(f'Browser setup: Creating Anchor Browser session for task {task.task_id}')
		cdp_url = await _retry_browser_creation(create_anchor_browser_session, 3, headless)
	elif browser == 'brightdata':
		if not BRIGHTDATA_CDP_URL:
			raise ValueError(f'Browser setup: Brightdata requested but BRIGHTDATA_CDP_URL not set for task {task.task_id}')

		logger.debug(f'Browser setup: Using Brightdata CDP URL for task {task.task_id}')
		cdp_url = BRIGHTDATA_CDP_URL
	elif browser == 'browserbase':
		if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT_ID:
			raise ValueError(
				f'Browser setup: Browserbase requested but BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set for task {task.task_id}'
			)

		logger.debug(f'Browser setup: Creating Browserbase session for task {task.task_id}')
		cdp_url = await _retry_browser_creation(create_browserbase_session, 3)
	elif browser == 'hyperbrowser':
		if not HYPERBROWSER_API_KEY:
			raise ValueError(f'Browser setup: Hyperbrowser requested but HYPERBROWSER_API_KEY not set for task {task.task_id}')

		logger.debug(f'Browser setup: Creating Hyperbrowser session for task {task.task_id}')
		cdp_url = await _retry_browser_creation(create_hyperbrowser_session, 3)
	elif browser == 'unikraft':
		if not UKC_TOKEN or not UKC_METRO:
			raise ValueError(f'Browser setup: Unikraft requested but UKC_TOKEN or UKC_METRO not set for task {task.task_id}')

		logger.debug(f'Browser setup: Creating Unikraft session for task {task.task_id}')
		cdp_url = await _retry_browser_creation(create_unikraft_session, 3, headless)
	elif browser == 'browser-use':
		raise NotImplementedError(f'Browser setup: Browser-use not implemented yet for task {task.task_id}')

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

	if browser == 'local':
		# Use local browser
		logger.debug(f'Browser setup: Initializing local BrowserSession for task {task.task_id}')
		browser_session = BrowserSession(browser_profile=profile)
	else:
		# All remote browsers should have provided a CDP URL or raised an exception
		if not cdp_url:
			raise RuntimeError(f'Browser setup: No CDP URL obtained for {browser} browser for task {task.task_id}')

		logger.debug(f'Browser setup: Using {browser} CDP Browser for task {task.task_id}')
		browser_session = BrowserSession(browser_profile=profile, cdp_url=cdp_url)

	# Start browser session
	await browser_session.start()
	logger.debug(f'Browser setup: Browser session started for task {task.task_id}')

	# Navigate to task starting url if provided
	# if task.website:
	# logger.debug(f'Browser setup: Navigating to {task.website} for task {task.task_id}')
	# await browser_session.navigate(task.website)

	logger.debug(f'Browser setup: Setup completed for task {task.task_id}')
	return browser_session
