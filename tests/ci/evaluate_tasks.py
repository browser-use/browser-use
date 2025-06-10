"""
Runs all agent tasks in parallel (up to 10 at a time) using separate subprocesses.
Each task gets its own Python process, preventing browser session interference.
Does not fail on partial failures (always exits 0).
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import sys
import warnings

import aiofiles
import yaml
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# --- CONFIG ---
MAX_PARALLEL = 10
TASK_DIR = (
	sys.argv[1]
	if len(sys.argv) > 1 and not sys.argv[1].startswith('--')
	else os.path.join(os.path.dirname(__file__), '../agent_tasks')
)
TASK_FILES = glob.glob(os.path.join(TASK_DIR, '*.yaml'))


class JudgeResponse(BaseModel):
	success: bool
	explanation: str


async def run_single_task(task_file):
	"""Run a single task in the current process (called by subprocess)"""
	try:
		print(f'[DEBUG] Starting task: {os.path.basename(task_file)}', file=sys.stderr)

		# Suppress all logging in subprocess to avoid interfering with JSON output
		logging.getLogger().setLevel(logging.CRITICAL)
		for logger_name in ['browser_use', 'telemetry', 'message_manager']:
			logging.getLogger(logger_name).setLevel(logging.CRITICAL)
		warnings.filterwarnings('ignore')

		print('[DEBUG] Loading task file...', file=sys.stderr)
		async with aiofiles.open(task_file, 'r') as f:
			content = await f.read()
		task_data = yaml.safe_load(content)
		task = task_data['task']
		judge_context = task_data.get('judge_context', ['The agent must solve the task'])
		max_steps = task_data.get('max_steps', 15)

		print(f'[DEBUG] Task: {task[:100]}...', file=sys.stderr)
		print(f'[DEBUG] Max steps: {max_steps}', file=sys.stderr)

		agent_llm = ChatOpenAI(model='gpt-4.1-mini')
		judge_llm = ChatOpenAI(model='gpt-4.1-mini')
		print('[DEBUG] LLMs initialized', file=sys.stderr)

		# Each subprocess gets its own profile and session
		print('[DEBUG] Creating browser session...', file=sys.stderr)
		profile = BrowserProfile(
			headless=True,
			user_data_dir=None,
			chromium_sandbox=False,  # Disable sandbox for CI environment (GitHub Actions)
			stealth=True,
		)
		session = BrowserSession(browser_profile=profile)
		print('[DEBUG] Browser session created', file=sys.stderr)

		# Test if browser is working
		try:
			await session.start()
			page = await session.create_page()
			print('[DEBUG] Browser test: page created successfully', file=sys.stderr)
			await page.goto('https://httpbin.org/get', timeout=10000)
			print('[DEBUG] Browser test: navigation successful', file=sys.stderr)
			title = await page.title()
			print(f"[DEBUG] Browser test: got title '{title}'", file=sys.stderr)
		except Exception as browser_error:
			print(f'[DEBUG] Browser test failed: {str(browser_error)}', file=sys.stderr)
			print(f'[DEBUG] Browser error type: {type(browser_error).__name__}', file=sys.stderr)

		print('[DEBUG] Starting agent execution...', file=sys.stderr)
		agent = Agent(task=task, llm=agent_llm, browser_session=session)

		try:
			history: AgentHistoryList = await agent.run(max_steps=max_steps)
			print('[DEBUG] Agent.run() returned successfully', file=sys.stderr)
		except Exception as agent_error:
			print(f'[DEBUG] Agent.run() failed with error: {str(agent_error)}', file=sys.stderr)
			print(f'[DEBUG] Error type: {type(agent_error).__name__}', file=sys.stderr)
			# Re-raise to be caught by outer try-catch
			raise agent_error

		agent_output = history.final_result() or ''
		print('[DEBUG] Agent execution completed', file=sys.stderr)

		# Test if LLM is working by making a simple call
		try:
			test_response = await agent_llm.ainvoke("Say 'test'")
			print(f'[DEBUG] LLM test call successful: {test_response.content[:50]}', file=sys.stderr)
		except Exception as llm_error:
			print(f'[DEBUG] LLM test call failed: {str(llm_error)}', file=sys.stderr)

		# Debug: capture more details about the agent execution
		total_steps = len(history.history) if hasattr(history, 'history') else 0
		last_action = history.history[-1] if hasattr(history, 'history') and history.history else None
		debug_info = f'Steps: {total_steps}, Final result length: {len(agent_output)}'
		if last_action:
			debug_info += f', Last action: {type(last_action).__name__}'

		# Log to stderr so it shows up in GitHub Actions (won't interfere with JSON output to stdout)
		print(f'[DEBUG] Task {os.path.basename(task_file)}: {debug_info}', file=sys.stderr)
		if agent_output:
			print(f'[DEBUG] Agent output preview: {agent_output[:200]}...', file=sys.stderr)
		else:
			print('[DEBUG] Agent produced no output!', file=sys.stderr)

		criteria = '\n- '.join(judge_context)
		judge_prompt = f"""
You are a evaluator of a browser agent task inside a ci/cd pipeline. Here was the agent's task:
{task}

Here is the agent's output:
{agent_output if agent_output else '[No output provided]'}

Debug info: {debug_info}

Criteria for success:
- {criteria}

Reply in JSON with keys: success (true/false), explanation (string).
If the agent provided no output, explain what might have gone wrong.
"""
		structured_llm = judge_llm.with_structured_output(JudgeResponse)
		judge_response = await structured_llm.ainvoke(judge_prompt)

		result = {
			'file': os.path.basename(task_file),
			'success': judge_response.success,
			'explanation': judge_response.explanation,
		}

		# Clean up session before returning
		await session.stop()

		return result

	except Exception as e:
		# Ensure session cleanup even on error
		try:
			await session.stop()
		except Exception:
			pass

		return {'file': os.path.basename(task_file), 'success': False, 'explanation': f'Task failed with error: {str(e)}'}


async def run_task_subprocess(task_file, semaphore):
	"""Run a task in a separate subprocess"""
	async with semaphore:
		try:
			# Set environment to reduce noise in subprocess
			env = os.environ.copy()
			env['PYTHONPATH'] = os.pathsep.join(sys.path)

			proc = await asyncio.create_subprocess_exec(
				sys.executable,
				__file__,
				'--task',
				task_file,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env,
			)
			stdout, stderr = await proc.communicate()

			if proc.returncode == 0:
				try:
					# Parse JSON result from subprocess
					stdout_text = stdout.decode().strip()
					stderr_text = stderr.decode().strip()

					# Display subprocess debug logs
					if stderr_text:
						print(f'[SUBPROCESS {os.path.basename(task_file)}] Debug output:')
						for line in stderr_text.split('\n'):
							if line.strip():
								print(f'  {line}')

					# Find the JSON line (should be the last line that starts with {)
					lines = stdout_text.split('\n')
					json_line = None
					for line in reversed(lines):
						line = line.strip()
						if line.startswith('{') and line.endswith('}'):
							json_line = line
							break

					if json_line:
						result = json.loads(json_line)
						print(f'[PARENT] Task {os.path.basename(task_file)} completed: {result["success"]}')
					else:
						raise ValueError(f'No JSON found in output: {stdout_text}')

				except (json.JSONDecodeError, ValueError) as e:
					result = {
						'file': os.path.basename(task_file),
						'success': False,
						'explanation': f'Failed to parse subprocess result: {str(e)[:100]}',
					}
					print(f'[PARENT] Task {os.path.basename(task_file)} failed to parse: {str(e)}')
					print(f'[PARENT] Full stdout was: {stdout.decode()[:500]}')
			else:
				stderr_text = stderr.decode().strip()
				result = {
					'file': os.path.basename(task_file),
					'success': False,
					'explanation': f'Subprocess failed (code {proc.returncode}): {stderr_text[:200]}',
				}
				print(f'[PARENT] Task {os.path.basename(task_file)} subprocess failed with code {proc.returncode}')
				if stderr_text:
					print(f'[PARENT] stderr: {stderr_text[:1000]}')
				stdout_text = stdout.decode().strip()
				if stdout_text:
					print(f'[PARENT] stdout: {stdout_text[:1000]}')
		except Exception as e:
			result = {
				'file': os.path.basename(task_file),
				'success': False,
				'explanation': f'Failed to start subprocess: {str(e)}',
			}
			print(f'[PARENT] Failed to start subprocess for {os.path.basename(task_file)}: {str(e)}')

		return result


async def main():
	"""Run all tasks in parallel using subprocesses"""
	semaphore = asyncio.Semaphore(MAX_PARALLEL)

	print(f'Found task files: {TASK_FILES}')

	if not TASK_FILES:
		print('No task files found!')
		return 0, 0

	# Run all tasks in parallel subprocesses
	tasks = [run_task_subprocess(task_file, semaphore) for task_file in TASK_FILES]
	results = await asyncio.gather(*tasks)

	passed = sum(1 for r in results if r['success'])
	total = len(results)

	print('\n' + '=' * 60)
	print(f'{"RESULTS":^60}\n')

	# Prepare table data
	headers = ['Task', 'Success', 'Reason']
	rows = []
	for r in results:
		status = '✅' if r['success'] else '❌'
		rows.append([r['file'], status, r['explanation']])

	# Calculate column widths
	col_widths = [max(len(str(row[i])) for row in ([headers] + rows)) for i in range(3)]

	# Print header
	header_row = ' | '.join(headers[i].ljust(col_widths[i]) for i in range(3))
	print(header_row)
	print('-+-'.join('-' * w for w in col_widths))

	# Print rows
	for row in rows:
		print(' | '.join(str(row[i]).ljust(col_widths[i]) for i in range(3)))

	print('\n' + '=' * 60)
	print(f'\n{"SCORE":^60}')
	print(f'\n{"=" * 60}\n')
	print(f'\n{"*" * 10}  {passed}/{total} PASSED  {"*" * 10}\n')
	print('=' * 60 + '\n')

	# Output results for GitHub Actions
	print(f'PASSED={passed}')
	print(f'TOTAL={total}')

	# Output detailed results as JSON for GitHub Actions
	detailed_results = []
	for r in results:
		detailed_results.append({'task': r['file'].replace('.yaml', ''), 'success': r['success'], 'reason': r['explanation']})

	print('DETAILED_RESULTS=' + json.dumps(detailed_results))

	return passed, total


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--task', type=str, help='Path to a single task YAML file (for subprocess mode)')
	args = parser.parse_args()

	if args.task:
		# Subprocess mode: run a single task and output ONLY JSON
		try:
			result = asyncio.run(run_single_task(args.task))
			# Output ONLY the JSON result, nothing else
			print(json.dumps(result))
		except Exception as e:
			# Even on critical failure, output valid JSON
			error_result = {
				'file': os.path.basename(args.task),
				'success': False,
				'explanation': f'Critical subprocess error: {str(e)}',
			}
			print(json.dumps(error_result))
	else:
		# Parent process mode: run all tasks in parallel subprocesses
		passed, total = asyncio.run(main())
		# Results already printed by main() function
