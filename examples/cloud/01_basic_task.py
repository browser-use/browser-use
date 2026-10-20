"""Run one Browser Use Cloud API V4 task."""

import os
import time
from math import isfinite
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv('BROWSER_USE_API_URL', 'https://api.browser-use.com/api/v4').rstrip('/')
API_KEY = os.getenv('BROWSER_USE_API_KEY')
if not API_KEY:
	raise RuntimeError('Set BROWSER_USE_API_KEY or add it to .env')

try:
	RUN_TIMEOUT_SECONDS = float(os.getenv('BROWSER_USE_RUN_TIMEOUT', '900'))
except ValueError as error:
	raise RuntimeError('BROWSER_USE_RUN_TIMEOUT must be a positive number of seconds') from error
if not isfinite(RUN_TIMEOUT_SECONDS) or RUN_TIMEOUT_SECONDS <= 0:
	raise RuntimeError('BROWSER_USE_RUN_TIMEOUT must be a positive number of seconds')
HEADERS = {'X-Browser-Use-API-Key': API_KEY}
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled'}


def create_run(task: str) -> str:
	response = requests.post(f'{API_URL}/runs', headers=HEADERS, json={'task': task}, timeout=30)
	response.raise_for_status()
	return response.json()['id']


def wait_for_run(run_id: str, poll_seconds: float = 2, timeout_seconds: float = RUN_TIMEOUT_SECONDS) -> dict[str, Any]:
	deadline = time.monotonic() + timeout_seconds

	while True:
		response = requests.get(f'{API_URL}/runs/{run_id}/status', headers=HEADERS, timeout=30)
		response.raise_for_status()
		status = response.json()['status']
		print(f'Status: {status}')

		if status in TERMINAL_STATUSES:
			break

		if time.monotonic() >= deadline:
			response = requests.post(f'{API_URL}/runs/{run_id}/cancel', headers=HEADERS, timeout=30)
			response.raise_for_status()
			raise TimeoutError(f'Cancelled run {run_id} after {timeout_seconds:g} seconds')

		time.sleep(poll_seconds)

	response = requests.get(f'{API_URL}/runs/{run_id}', headers=HEADERS, timeout=30)
	response.raise_for_status()
	return response.json()


def main() -> None:
	run_id = create_run('Find the top story on Hacker News and summarize it in one sentence.')
	print(f'Run: {run_id}')

	run = wait_for_run(run_id)
	if run['status'] != 'completed':
		raise RuntimeError(run.get('error') or f'Run {run["status"]}')

	print(f'Result: {run["result"]}')
	print(f'Cost: ${run["totalCostUsd"]}')


if __name__ == '__main__':
	main()
