import os
import time

import requests
from dotenv import load_dotenv


load_dotenv()


BASE_URL = 'https://api.browser-use.com/api/v4'
POLL_INTERVAL = 3
MAX_WAIT_TIME = 180


def run_browser_task(task: str):
	start_time = time.time()

	api_key = os.getenv('BROWSER_USE_API_KEY')

	if not api_key:
		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': 0,
			'error': 'BROWSER_USE_API_KEY is not loaded.',
		}

	headers = {
		'X-Browser-Use-API-Key': api_key,
		'Content-Type': 'application/json',
	}

	try:
		# Submit browser task
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

		# Poll until the task completes
		while time.time() - start_time < MAX_WAIT_TIME:
			time.sleep(POLL_INTERVAL)

			status_response = requests.get(
				f'{BASE_URL}/runs/{run_id}',
				headers=headers,
				timeout=30,
			)

			status_response.raise_for_status()

			run_data = status_response.json()
			status = run_data.get('status')

			print(f'[INFO] Status: {status}')

			if status == 'completed':
				result = run_data.get('result')

				return {
					'success': bool(result),
					'task': task,
					'result': result,
					'execution_time': round(time.time() - start_time, 2),
					'error': run_data.get('error'),
				}

			if status in {'failed', 'cancelled', 'stopped'}:
				return {
					'success': False,
					'task': task,
					'result': run_data.get('result'),
					'execution_time': round(time.time() - start_time, 2),
					'error': run_data.get('error') or f'Task {status}.',
				}

		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': 'Browser task timed out.',
		}

	except requests.RequestException as e:
		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': f'Browser Use API request failed: {e}',
		}

	except Exception as e:
		return {
			'success': False,
			'task': task,
			'result': None,
			'execution_time': round(time.time() - start_time, 2),
			'error': str(e),
		}
