import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = 'https://api.browser-use.com/api/v4'
POLL_INTERVAL = 3
MAX_WAIT_TIME = 180


def cancel_run(run_id: str, headers: dict[str, str]) -> None:
	"""Cancel a hosted Browser Use run after a local timeout."""
	try:
		response = requests.post(
			f'{BASE_URL}/runs/{run_id}/cancel',
			headers=headers,
			timeout=30,
		)
		response.raise_for_status()
		print(f'[INFO] Cancelled timed-out run: {run_id}')
	except requests.RequestException as exc:
		print(f'[WARNING] Failed to cancel run {run_id}: {exc}')


def run_browser_task(task: str):
	start_time = time.time()

	api_key = os.getenv('BROWSER_USE_API_KEY')

	if not api_key:
		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': 0,
			'error': 'BROWSER_USE_API_KEY is not configured.',
		}

	headers = {
		'X-Browser-Use-API-Key': api_key,
		'Content-Type': 'application/json',
	}

	try:
		response = requests.post(
			f'{BASE_URL}/runs',
			headers=headers,
			json={'task': task},
			timeout=30,
		)
		response.raise_for_status()

		run_data = response.json()
		run_id = run_data['id']

		print('\n[INFO] Browser task submitted.')
		print(f'[INFO] Run ID: {run_id}')

		while time.time() - start_time < MAX_WAIT_TIME:
			time.sleep(POLL_INTERVAL)

			status_response = requests.get(
				f'{BASE_URL}/runs/{run_id}/status',
				headers=headers,
				timeout=30,
			)
			status_response.raise_for_status()

			status_data = status_response.json()
			status = status_data.get('status')

			print(f'[INFO] Status: {status}')

			if status in {'completed', 'failed', 'cancelled', 'stopped'}:
				final_response = requests.get(
					f'{BASE_URL}/runs/{run_id}',
					headers=headers,
					timeout=30,
				)
				final_response.raise_for_status()

				run_data = final_response.json()

				if status == 'completed':
					result = run_data.get('result')

					return {
						'success': bool(result),
						'task': task,
						'result': result,
						'execution_time': round(time.time() - start_time, 2),
						'error': run_data.get('error'),
					}

				return {
					'success': False,
					'task': task,
					'result': run_data.get('result'),
					'execution_time': round(time.time() - start_time, 2),
					'error': run_data.get('error') or f'Task {status}.',
				}

		cancel_run(run_id, headers)

		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': 'Browser research timed out and the hosted run was cancelled.',
		}

	except requests.RequestException as exc:
		print(f'[ERROR] Browser Use API request failed: {exc}')

		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': 'Browser Use API request failed. Please try again.',
		}

	except (KeyError, ValueError) as exc:
		print(f'[ERROR] Invalid Browser Use API response: {exc}')

		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': 'Browser Use returned an invalid response.',
		}

	except Exception as exc:
		print(f'[ERROR] Unexpected browser task failure: {exc}')

		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': 'An unexpected error occurred while running the browser task.',
		}
