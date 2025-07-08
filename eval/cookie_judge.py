import json
import logging
import time
from pathlib import Path

import anyio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Global tracking for login cookie monitoring
_login_cookie_tracker = {}


async def check_login_cookie_at_step(browser_session, task_id: str, login_cookie: str, step: int) -> bool:
	global _login_cookie_tracker

	try:
		# Get current cookies from browser
		current_cookies = await browser_session.get_cookies()

		if not current_cookies:
			logger.debug(f'Task {task_id} Step {step}: No cookies found')
			return False

		# Check if this is an exact match requirement
		if login_cookie.startswith('EXACTMATCH '):
			exact_cookie_name = login_cookie[11:]  # Remove "EXACTMATCH " prefix
			is_exact_match = True
			search_target = exact_cookie_name
		else:
			is_exact_match = False
			search_target = login_cookie

		# Check if login_cookie is present
		for cookie in current_cookies:
			cookie_name = cookie.get('name', '')
			cookie_value = cookie.get('value', '')

			if is_exact_match:
				if cookie_name == search_target:
					logger.info(f'✅ Task {task_id} Step {step}: Login cookie "{search_target}" found (exact match)')
					# Track that we found the cookie
					_login_cookie_tracker[task_id] = {
						'found': True,
						'step': step,
						'cookie_name': cookie_name,
						'match_type': 'exact',
					}
					return True
			else:
				if search_target in cookie_name or search_target in cookie_value:
					logger.info(f'✅ Task {task_id} Step {step}: Login cookie "{search_target}" found (substring match)')
					# Track that we found the cookie
					_login_cookie_tracker[task_id] = {
						'found': True,
						'step': step,
						'cookie_name': cookie_name,
						'match_type': 'substring',
					}
					return True

		logger.debug(f'Task {task_id} Step {step}: Login cookie "{search_target}" not found in {len(current_cookies)} cookies')
		return False

	except Exception as e:
		logger.warning(f'Task {task_id} Step {step}: Error checking login cookie: {type(e).__name__}: {e}')
		return False


async def save_login_cookie_tracking(task_folder: Path, task_id: str) -> None:
	"""
	Save the login cookie tracking information to a file.

	Args:
		task_folder: Directory to save the tracking file
		task_id: The task ID
	"""
	global _login_cookie_tracker

	try:
		tracking_file = task_folder / 'login_cookie_tracking.json'
		tracking_data = _login_cookie_tracker.get(task_id, {'found': False})

		# Add timestamp
		tracking_data['timestamp'] = time.time()

		# Save to file
		async with await anyio.open_file(tracking_file, 'w') as f:
			await f.write(json.dumps(tracking_data, indent=2))

		logger.info(f'📝 Saved login cookie tracking for task {task_id}: {tracking_data}')

		# Clean up tracking data to avoid memory leaks
		_login_cookie_tracker.pop(task_id, None)

	except Exception as e:
		logger.warning(f'❌ Failed to save login cookie tracking for task {task_id}: {type(e).__name__}: {e}')


async def evaluate_task_with_login_cookie(login_cookie: str, task_folder: Path) -> dict:
	task_id = task_folder.name

	# First, check if we have step-by-step tracking data
	tracking_file = task_folder / 'login_cookie_tracking.json'
	if tracking_file.exists():
		try:
			async with await anyio.open_file(tracking_file) as f:
				tracking_data = json.loads(await f.read())

			if tracking_data.get('found', False):
				# Cookie was found during execution!
				step_found = tracking_data.get('step', 'unknown')
				match_type = tracking_data.get('match_type', 'unknown')
				cookie_name = tracking_data.get('cookie_name', 'unknown')

				success = True
				score = 1.0
				judgement = f"Automatic judgement: Login cookie '{login_cookie}' was found during step {step_found} ({match_type} match on '{cookie_name}')"
				error = None

				logger.info(
					f"✅ Cookie evaluation result from step tracking: success={success} for login_cookie='{login_cookie}'"
				)

				return {
					'task_id': task_id,
					'judgement': judgement,
					'success': success,
					'error': error,
					'score': score,
					'tracking_data': tracking_data,
				}
		except Exception as e:
			logger.warning(f'Failed to load login cookie tracking: {e}')

	# Fallback to end-state cookie checking (original behavior)
	logger.info(f'🔄 No step-by-step tracking found for task {task_id}, falling back to end-state cookie checking')

	# Look for cookies in saved_trajectories (saved by browser-use during shutdown)
	cookies_file = task_folder / 'cookies.json'
	storage_state_file = task_folder / 'storage_state.json'

	cookies_data = None
	cookies_source = None

	# Try to load cookies from storage_state.json first (newer format)
	if storage_state_file.exists():
		try:
			async with await anyio.open_file(storage_state_file) as f:
				storage_state = json.loads(await f.read())
				cookies_data = storage_state.get('cookies', [])
				cookies_source = 'storage_state.json'
		except Exception as e:
			logger.warning(f'Failed to load storage_state.json: {e}')

	# Fallback to cookies.json (older format)
	if not cookies_data and cookies_file.exists():
		try:
			async with await anyio.open_file(cookies_file) as f:
				cookies_data = json.loads(await f.read())
				cookies_source = 'cookies.json'
		except Exception as e:
			logger.warning(f'Failed to load cookies.json: {e}')

	if not cookies_data:
		return {
			'task_id': task_id,
			'judgement': 'Automatic judgement: No cookies saved for evaluation and no step-by-step tracking',
			'success': False,
			'error': 'No cookies file found for login task evaluation and no step-by-step tracking',
			'score': 0.0,
		}

	logger.debug(f'Found {len(cookies_data)} cookies from {cookies_source}')

	# Check if this is an exact match requirement
	if login_cookie.startswith('EXACTMATCH '):
		# Extract the actual cookie name after "EXACTMATCH "
		exact_cookie_name = login_cookie[11:]  # Remove "EXACTMATCH " prefix
		is_exact_match = True
		search_target = exact_cookie_name
		logger.debug(f"Using exact match for cookie name: '{exact_cookie_name}'")
	else:
		# Use substring matching (original behavior)
		is_exact_match = False
		search_target = login_cookie
		logger.debug(f"Using substring matching for: '{login_cookie}'")

	# Check if login_cookie is present in cookies
	login_cookie_found = False
	matching_cookie_info = None

	for cookie in cookies_data:
		cookie_name = cookie.get('name', '')
		cookie_value = cookie.get('value', '')

		if is_exact_match:
			# Exact match: check if cookie name exactly matches the target
			if cookie_name == search_target:
				login_cookie_found = True
				matching_cookie_info = f"exact name match='{cookie_name}'"
				logger.debug(f'Login cookie found with exact match: {matching_cookie_info}')
				break
		else:
			# Substring match: check if target appears in cookie name or value
			if search_target in cookie_name or search_target in cookie_value:
				login_cookie_found = True
				matching_cookie_info = f"substring match in name='{cookie_name}'"
				logger.debug(f'Login cookie found with substring match: {matching_cookie_info}')
				break

	# Prepare evaluation result
	if login_cookie_found:
		if is_exact_match:
			judgement = (
				f"Automatic judgement: Login cookie '{search_target}' was found as exact match in end-state browser cookies"
			)
		else:
			judgement = f"Automatic judgement: Login cookie '{search_target}' was found in end-state browser cookies"
		success = True
		score = 1.0
		error = None
	else:
		if is_exact_match:
			judgement = (
				f"Automatic judgement: Login cookie '{search_target}' was NOT found as exact match in end-state browser cookies"
			)
		else:
			judgement = f"Automatic judgement: Login cookie '{search_target}' was NOT found in end-state browser cookies"
		success = False
		score = 0.0
		error = None

	logger.info(f"Cookie evaluation result from end-state: success={success} for login_cookie='{login_cookie}'")

	return {
		'task_id': task_id,
		'judgement': judgement,
		'success': success,
		'error': error,
		'score': score,
	}
