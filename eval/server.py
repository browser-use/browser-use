import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


def fetch_tasks_from_server(convex_url: str, secret_key: str, test_case_name: str):
	"""Fetches the specified test case file from the Convex HTTP endpoint."""

	if not convex_url:
		logger.error('Error: EVALUATION_TOOL_URL environment variable not set.')
		return None

	if not secret_key:
		logger.error('Error: EVALUATION_TOOL_SECRET_KEY environment variable not set.')
		return None

	endpoint_url = f'{convex_url}/api/getTestCase'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}
	payload = {'name': test_case_name}

	logger.info(f"Fetching test case '{test_case_name}' from {endpoint_url}...")

	try:
		response = requests.post(endpoint_url, headers=headers, json=payload, timeout=10)

		logger.info(f'Fetch Status Code: {response.status_code}')

		if response.status_code == 200:
			try:
				data = response.json()
				logger.info(f"Successfully fetched test case data for '{test_case_name}'.")
				# Assuming the data is the list of tasks
				if isinstance(data, list):
					return data
				else:
					logger.error(f'Error: Fetched data is not a list. Type: {type(data)}')
					logger.error(f'Raw response: {response.text}')
					return None

			except json.JSONDecodeError:
				logger.error('Error: Failed to decode JSON response.')
				logger.error(f'Raw response text: {response.text}')
				return None
		else:
			logger.error(f"Error: Failed to fetch test case '{test_case_name}'. Status: {response.status_code}")
			logger.error(f'Response: {response.text}')
			return None

	except requests.exceptions.RequestException as e:
		logger.error(f'Error during request to fetch test case: {type(e).__name__}: {e}')
		return None


def fetch_auth_distribution_from_server(convex_url: str, secret_key: str):
	"""Fetches an available auth distribution from the Convex HTTP endpoint."""

	if not convex_url:
		logger.error('Error: EVALUATION_TOOL_URL environment variable not set.')
		return None

	if not secret_key:
		logger.error('Error: EVALUATION_TOOL_SECRET_KEY environment variable not set.')
		return None

	endpoint_url = f'{convex_url}/api/getAuthDistribution'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}

	logger.info(f'Fetching auth distribution from {endpoint_url}...')

	try:
		response = requests.post(endpoint_url, headers=headers, json={}, timeout=10)

		logger.info(f'Fetch Auth Distribution Status Code: {response.status_code}')

		if response.status_code == 200:
			try:
				data = response.json()
				logger.info('Successfully fetched auth distribution data.')
				# Verify the response has the expected structure
				if isinstance(data, dict) and 'id' in data and 'loginInfo' in data:
					return data
				else:
					logger.error(
						f'Error: Fetched auth distribution data has unexpected structure. Keys: {list(data.keys()) if isinstance(data, dict) else "Not a dict"}'
					)
					logger.error(f'Raw response: {response.text}')
					return None

			except json.JSONDecodeError:
				logger.error('Error: Failed to decode JSON response for auth distribution.')
				logger.error(f'Raw response text: {response.text}')
				return None
		elif response.status_code == 404:
			logger.warning('No available auth distribution found on server.')
			return None
		else:
			logger.error(f'Error: Failed to fetch auth distribution. Status: {response.status_code}')
			logger.error(f'Response: {response.text}')
			return None

	except requests.exceptions.RequestException as e:
		logger.error(f'Error during request to fetch auth distribution: {type(e).__name__}: {e}')
		return None


def format_auth_info_for_agent(auth_distribution: dict, auth_keys: list[str]) -> str:
	"""
	Formats auth information from auth distribution for the agent task description.

	Args:
		auth_distribution: Dict with 'loginInfo' key containing auth data
		auth_keys: List of auth keys to extract (e.g., ['google', 'facebook'])

	Returns:
		Formatted string with login credentials or empty string if no matching keys
	"""
	if not auth_distribution or not auth_keys:
		return ''

	login_info = auth_distribution.get('loginInfo', {})
	if not login_info:
		logger.warning('Auth distribution has no loginInfo')
		return ''

	# Extract relevant auth information based on auth_keys
	relevant_auths = []
	for auth_key in auth_keys:
		if auth_key in login_info:
			auth_data = login_info[auth_key]
			if isinstance(auth_data, dict):
				# Format the auth data for this key
				auth_details = []
				for key, value in auth_data.items():
					auth_details.append(f'{key}: {value}')

				if auth_details:
					relevant_auths.append(f'{auth_key} with {", ".join(auth_details)}')
			else:
				logger.warning(f"Auth data for key '{auth_key}' is not a dictionary: {type(auth_data)}")
		else:
			logger.warning(f"Auth key '{auth_key}' not found in available login info. Available keys: {list(login_info.keys())}")

	if relevant_auths:
		auth_text = f'\n\nThe following login credentials can be used to complete this task: {"; ".join(relevant_auths)}.'
		logger.info(f'Formatted auth info: {auth_text}')
		return auth_text
	else:
		logger.warning(f'No matching auth keys found. Requested: {auth_keys}, Available: {list(login_info.keys())}')
		return ''


def start_new_run(convex_url: str, secret_key: str, run_details: dict, existing_run_id: str | None = None):
	"""Sends a request to start a new evaluation run and returns the run ID."""
	if not convex_url or not secret_key:
		logger.error('Error: Convex URL or Secret Key not provided for starting run.')
		return None

	endpoint_url = f'{convex_url}/api/startRun'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}

	# Add existing_run_id to the payload if provided
	payload = run_details.copy()
	if existing_run_id:
		payload['runId'] = existing_run_id

	logger.info(f'Sending request to start run at {endpoint_url}...')
	# Avoid logging secret key in run_details if it were ever passed
	loggable_details = {k: v for k, v in payload.items() if k != 'secret_key'}
	logger.info(f'Run details: {json.dumps(loggable_details, indent=2)}')

	try:
		response = requests.post(endpoint_url, headers=headers, json=payload, timeout=10)
		logger.info(f'Start Run Status Code: {response.status_code}')

		if response.status_code == 200:
			try:
				data = response.json()
				run_id = data.get('runId')
				if run_id:
					logger.info(f'Successfully started run. Run ID: {run_id}')
					return run_id
				else:
					logger.error("Error: 'runId' not found in successful startRun response.")
					logger.error(f'Raw response: {response.text}')
					return None
			except json.JSONDecodeError:
				logger.error('Error: Failed to decode startRun JSON response.')
				logger.error(f'Raw response text: {response.text}')
				return None
		else:
			logger.error('Error: Failed to start run.')
			logger.error(f'Response: {response.text}')
			return None

	except requests.exceptions.RequestException as e:
		logger.error(f'Error during startRun request: {type(e).__name__}: {e}')
		return None


def save_task_result_to_server(convex_url: str, secret_key: str, result_details: dict):
	"""Sends a request to save a single task result to the Convex backend."""

	if not convex_url:
		logger.error('Error: EVALUATION_TOOL_URL environment variable not set for saving task result.')
		return False

	if not secret_key:
		logger.error('Error: EVALUATION_TOOL_SECRET_KEY environment variable not set for saving task result.')
		return False

	# Ensure runId is present in the details being sent
	if 'runId' not in result_details or not result_details['runId']:
		logger.error("Error: 'runId' is missing or empty in result_details for saveTaskResult.")
		return False

	endpoint_url = f'{convex_url}/api/saveTaskResult'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}

	logger.info(f'Sending request to save task result at {endpoint_url}...')
	logger.debug(f'Result details payload: {json.dumps(result_details, indent=2)}')  # Log details at debug level

	try:
		response = requests.post(endpoint_url, headers=headers, json=result_details, timeout=10)

		logger.info(f'Save Task Result Status Code: {response.status_code}')

		if response.status_code == 200:
			try:
				data = response.json()
				logger.info(f'Successfully saved task result: {data.get("message")}')
				logger.info(f'Result ID: {data.get("resultId")}')
				return True
			except json.JSONDecodeError:
				logger.error('Error: Failed to decode saveTaskResult JSON response.')
				logger.error(f'Raw response text: {response.text}')
				return False
		else:
			logger.error('Error: Failed to save task result.')
			logger.error(f'Response: {response.text}')
			return False

	except requests.exceptions.RequestException as e:
		logger.error(f'Error during saveTaskResult request: {type(e).__name__}: {e}')
		return False


def save_runner_progress_to_server(convex_url: str, secret_key: str, progress_details: dict):
	"""Sends a request to save runner progress to the Convex backend."""

	if not convex_url:
		logger.debug('No EVALUATION_TOOL_URL environment variable set for saving runner progress.')
		return False

	if not secret_key:
		logger.debug('No EVALUATION_TOOL_SECRET_KEY environment variable set for saving runner progress.')
		return False

	endpoint_url = f'{convex_url}/api/saveRunnerProgress'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}

	try:
		response = requests.post(endpoint_url, headers=headers, json=progress_details, timeout=10)

		if response.status_code == 200:
			logger.debug(f'Successfully saved runner progress for {progress_details.get("runnerId")}')
			return True
		else:
			logger.warning(f'Failed to save runner progress. Status: {response.status_code}')
			return False

	except requests.exceptions.RequestException as e:
		logger.warning(f'Error during saveRunnerProgress request: {type(e).__name__}: {e}')
		return False


def generate_runner_id(task_id: str, github_run_id: str | None = None) -> str:
	"""Generate a unique runner ID for progress tracking that matches GitHub Actions pattern"""
	if github_run_id:
		# Use batch-level runner ID consistent with GitHub Actions
		# GitHub Actions uses: github_run_{GITHUB_RUN_ID}_batch_{START_INDEX}
		# Get start index from environment variable set by GitHub Actions
		start_index = os.getenv('EVAL_START_INDEX', '0')
		return f'github_run_{github_run_id}_batch_{start_index}'
	else:
		# Fallback for local runs
		return f'local_run_{int(time.time())}'


def send_progress_update(
	convex_url: str,
	secret_key: str,
	run_id: str,
	task_id: str,
	current_stage: str,
	status: str = 'active',
	github_workflow_url: str | None = None,
	assigned_task_range: str | None = None,
	error_message: str | None = None,
) -> bool:
	"""Send a progress update for the current runner and task"""
	try:
		# Generate runner ID
		github_run_id = os.getenv('GITHUB_RUN_ID')
		runner_id = generate_runner_id(task_id, github_run_id)

		# Extract workflow run ID from URL if available
		github_workflow_run_id = None
		if github_workflow_url and 'actions/runs/' in github_workflow_url:
			try:
				github_workflow_run_id = github_workflow_url.split('actions/runs/')[1].split('/')[0]
			except (IndexError, AttributeError):
				pass

		progress_details = {
			'runId': run_id,
			'runnerId': runner_id,
			'taskId': task_id,
			'currentStage': current_stage,
			'status': status,
			'githubWorkflowUrl': github_workflow_url,
			'githubWorkflowRunId': github_workflow_run_id,
			'assignedTaskRange': assigned_task_range,
			'errorMessage': error_message,
		}

		return save_runner_progress_to_server(convex_url, secret_key, progress_details)
	except Exception as e:
		logger.warning(f'Failed to send progress update: {type(e).__name__}: {e}')
		return False
