# ================================================
# Imports
# ================================================

import argparse
import asyncio
import base64
import http.client
import json
import logging
import os
import time
from pathlib import Path
from uuid import UUID

import anyio
from dotenv import load_dotenv
from lmnr import AsyncLaminarClient, Instruments, Laminar
from pydantic import BaseModel

from browser_use import ActionResult, Agent, BrowserSession, Controller
from browser_use.agent.views import AgentHistoryList
from browser_use.llm.base import BaseChatModel
from browser_use.observability import observe, observe_debug

MAX_IMAGE = 5
from eval.browsers import (
	ANCHOR_BROWSER_API_KEY,
	BRIGHTDATA_CDP_URL,
	BROWSERBASE_API_KEY,
	BROWSERBASE_PROJECT_ID,
	HYPERBROWSER_API_KEY,
	setup_browser_session,
)
from eval.comprehensive_judge import evaluate_task_with_comprehensive_judge
from eval.cookie_judge import check_login_cookie_at_step, evaluate_task_with_login_cookie, save_login_cookie_tracking
from eval.models import SUPPORTED_MODELS, get_llm
from eval.resource_monitoring import (
	get_system_resources,
	log_system_resources,
	setup_signal_handlers,
	start_resource_monitoring,
	stop_resource_monitoring,
)
from eval.server import (
	fetch_auth_distribution_from_server,
	fetch_tasks_from_server,
	format_auth_info_for_agent,
	save_task_result_to_server,
	send_progress_update,
	start_new_run,
)
from eval.task_types import Stage, StageError, Task, TaskResult
from eval.utils import get_git_info
from eval.web_judge import Online_Mind2Web_eval_with_retry

# ================================================
# Setup Logging
# ================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# ================================================
# Environment variables
# ================================================

# Load dotenv
load_dotenv()

# Check for SERPER API key
SERPER_API_KEY = os.getenv('SERPER_API_KEY')
if not SERPER_API_KEY:
	logger.warning('SERPER_API_KEY is not set. Search functionality will not be available.')


# ================================================
# Tracking and Observations
# ================================================

Laminar.initialize(disabled_instruments={Instruments.BROWSER_USE}, disable_batch=True)
laminar_client = AsyncLaminarClient()

# Resource monitoring functions moved to resource_monitoring.py module


# ================================================
# Custom Controllers
# ================================================


def create_controller_with_serp_search(output_model: type[BaseModel] | None = None):
	"""Create a controller with SERP search instead of Google search"""
	controller = Controller(exclude_actions=['search_google'], output_model=output_model)

	@controller.registry.action('Search the web for a specific query')
	async def search_web(query: str):
		"""Search the web using Serper API"""
		if not SERPER_API_KEY:
			return ActionResult(extracted_content='Search unavailable: SERPER_API_KEY not configured', include_in_memory=True)

		try:
			# Make request to Serper API
			conn = http.client.HTTPSConnection('google.serper.dev')
			payload = json.dumps({'q': query})
			headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
			conn.request('POST', '/search', payload, headers)
			res = conn.getresponse()
			data = res.read()
			serp_data = json.loads(data.decode('utf-8'))

			# Exclude searchParameters and credits to reduce noise
			serp_data = {k: v for k, v in serp_data.items() if k not in ['searchParameters', 'credits']}

			# Log the search data for debugging
			logger.debug(f"SERP search for '{query}': {json.dumps(serp_data, indent=2)}")

			# Convert to string for the agent
			serp_data_str = json.dumps(serp_data)

			return ActionResult(
				extracted_content=serp_data_str, include_in_memory=False, include_extracted_content_only_once=True
			)

		except Exception as e:
			logger.error(f'Error in SERP search: {type(e).__name__}: {e}')
			return ActionResult(error=f'Search error: {str(e)}')

	return controller


def create_controller(
	use_serp: bool = False,
	output_model: type[BaseModel] | None = None,
	gmail_tokens_dict: dict[str, str] | None = None,
	task: 'Task | None' = None,
):
	"""Create a controller, optionally with SERP search and Gmail 2FA support"""
	if use_serp:
		controller = create_controller_with_serp_search(output_model=output_model)
	else:
		controller = Controller(output_model=output_model)

	# Add Gmail 2FA support if tokens dict is available and task has login_type OTP
	if gmail_tokens_dict and task and hasattr(task, 'login_type') and task.login_type == 'OTP':
		try:
			# Extract username from task - check multiple possible sources
			username = None

			# Check if task has email field directly
			if hasattr(task, 'username') and getattr(task, 'username', None):
				username = getattr(task, 'username')
			# Check if email is in task description or other fields
			elif hasattr(task, 'confirmed_task') and '@' in task.confirmed_task:
				# Extract email from task description using regex
				import re

				email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
				matches = re.findall(email_pattern, task.confirmed_task)
				if matches:
					username = matches[0]

			if username:
				# Extract user ID (part before @)
				user_id = username.split('@')[0]

				# Look up access token in the dictionary
				access_token = gmail_tokens_dict.get(user_id)

				if access_token:
					from browser_use.integrations.gmail import register_gmail_actions

					# Register Gmail actions using the access token
					controller = register_gmail_actions(controller, access_token=access_token)
					logger.info(f'Gmail 2FA integration registered successfully for user {user_id} (OTP task)')
				else:
					logger.info(f'No Gmail 2FA token found for user {user_id}, running without Gmail integration')
			else:
				logger.info('No email found in OTP task, running without Gmail integration')

		except Exception as e:
			logger.error(f'Failed to setup Gmail integration: {e}')
	else:
		if gmail_tokens_dict and task:
			if not hasattr(task, 'login_type') or task.login_type != 'OTP':
				logger.info(f'Task login_type is "{getattr(task, "login_type", "None")}", not OTP - skipping Gmail integration')
			else:
				logger.info('Gmail 2FA tokens provided but no task or task missing login_type')
		else:
			logger.info('No Gmail 2FA tokens provided or no task, running without Gmail integration')

	return controller


# ================================================
# Formatting results
# ================================================


def clean_action_dict(action_dict: dict) -> dict:
	return {k: clean_action_dict(v) if isinstance(v, dict) else v for k, v in action_dict.items() if v is not None}


async def reformat_agent_history(
	agent_history: AgentHistoryList,
	task_id: str,
	run_id: str,
	task: str,
	last_message: str,
	base_path: str = 'saved_trajectories',
	include_result: bool = False,
	agent_execution_time: float | None = None,
) -> dict:
	# Update directory name
	task_dir = Path(base_path) / task_id
	trajectory_with_highlights_dir = task_dir / 'trajectory_with_highlights'

	# Create directories
	task_dir.mkdir(parents=True, exist_ok=True)
	trajectory_with_highlights_dir.mkdir(parents=True, exist_ok=True)

	# Collect screenshot paths and action history
	screenshot_paths = []
	action_history = []
	final_result = None
	self_report_completed = False
	self_report_success = None
	complete_history = []
	total_tokens_used = 0  # Initialize token counter

	# Process history items
	for step_num, history_item in enumerate(agent_history.history):
		# Save screenshot
		if history_item.state and history_item.state.screenshot:
			screenshot_path = trajectory_with_highlights_dir / f'step_{step_num}.png'
			screenshot_paths.append(str(screenshot_path))
			# Save the actual screenshot
			screenshot_data = base64.b64decode(history_item.state.screenshot)
			async with await anyio.open_file(screenshot_path, 'wb') as f:
				await f.write(screenshot_data)

		# Get action result content
		if history_item.result:
			for result in history_item.result:
				# We don't want to include the final result in the action history as per the evaluation criteria
				if result.extracted_content and result.extracted_content != 'None' and not result.is_done:
					action_history.append(result.extracted_content)
				# Check if this is the final result
				if result.is_done:
					final_result = result.extracted_content
					self_report_completed = True
					self_report_success = result.success

		# Build complete history entry with cleaned model output
		model_output = None
		if history_item.model_output:
			model_output = history_item.model_output.model_dump()
			if 'action' in model_output:
				# Clean each action in the action list
				model_output['action'] = [clean_action_dict(action) for action in model_output['action']]

		step_metadata = history_item.metadata.model_dump() if history_item.metadata else {}
		step_info = {
			'step_number': step_num,
			'model_output': model_output,
			'result': [r.model_dump() for r in history_item.result] if history_item.result else None,
			'state': {
				'url': history_item.state.url if history_item.state else None,
				'title': history_item.state.title if history_item.state else None,
			},
			'metadata': step_metadata,  # Use dumped metadata
		}
		complete_history.append(step_info)

		# Sum up tokens from metadata
		if step_metadata and 'input_tokens' in step_metadata:
			try:
				total_tokens_used += int(step_metadata['input_tokens'])
			except (ValueError, TypeError):
				logger.warning(
					f"Task {task_id}, Step {step_num}: Could not parse input_tokens '{step_metadata['input_tokens']}' as integer."
				)

	# Calculate task duration from metadata (step-based timing)
	step_based_duration = None
	if complete_history and len(complete_history) > 0:
		first_step = complete_history[0].get('metadata', {})
		last_step = complete_history[-1].get('metadata', {})
		if first_step and last_step:
			start_time = first_step.get('step_start_time')
			end_time = last_step.get('step_end_time')
			if start_time and end_time:
				# Ensure timestamps are floats before subtracting
				try:
					start_time_float = float(start_time)
					end_time_float = float(end_time)
					step_based_duration = end_time_float - start_time_float
				except (ValueError, TypeError) as e:
					logger.warning(f'Could not calculate step-based duration due to invalid timestamp format: {e}')

	# Use agent execution time if provided (wall-clock timing around run_agent), otherwise fall back to step-based
	task_duration = agent_execution_time if agent_execution_time is not None else step_based_duration

	# Conditionally include the final result in action history
	if include_result and final_result and final_result.strip():
		action_history = action_history + [final_result]

	# Extract usage data from agent history
	usage_data = None
	logger.info(f'Agent history usage object: {agent_history.usage}')
	logger.info(f'Agent history usage type: {type(agent_history.usage)}')
	if hasattr(agent_history, 'usage') and agent_history.usage:
		logger.info(f'Agent history usage model_dump: {agent_history.usage.model_dump()}')
		usage_data = agent_history.usage.model_dump()
	else:
		logger.warning('Agent history has no usage data or usage is empty/None')

	# Create results structure with new fields
	results = {
		'task_id': task_id,
		'run_id': run_id,
		'task': task,
		'action_history': action_history,
		'screenshot_paths': screenshot_paths,
		'final_result_response': final_result,
		'last_message': last_message,
		'self_report_completed': self_report_completed,
		'self_report_success': self_report_success,
		'complete_history': complete_history,
		'task_duration': task_duration,
		'steps': len(complete_history),
		'tokensUsed': total_tokens_used,  # Add total tokens used
		'usage': usage_data,  # Add usage data
	}

	# Save results file
	results_path = task_dir / 'result.json'
	async with await anyio.open_file(results_path, 'w') as f:
		# Use a custom JSON encoder to handle potential non-serializable types like Path
		await f.write(json.dumps(results, indent=2, default=str))

	return results


# ================================================
# Judge task result
# ================================================


@observe_debug()
async def judge_task_result(
	model, task_folder: Path, score_threshold: float = 3, use_mind2web: bool = False, judge_repeat_count: int = 1
) -> dict:
	"""
	Judge a single task result using the comprehensive judge system by default,
	with optional fallback to the original Online_Mind2Web evaluation.

	Args:
	    model: The model to use for evaluation
	    task_folder: Path to the task result folder
	    score_threshold: Score threshold for image filtering (used only for Mind2Web)
	    use_mind2web: If True, use the original Online_Mind2Web evaluation instead
	    judge_repeat_count: Number of times to repeat the judge evaluation (averages over multiple judgments)

	Returns:
	    Dictionary containing judgment results
	"""
	result_file = task_folder / 'result.json'
	if not result_file.exists():
		return {
			'task_id': task_folder.name,
			'judgement': 'No result.json found',
			'success': False,
			'error': 'No result.json found',
			'score': 0.0,
		}

	try:
		async with await anyio.open_file(result_file) as f:
			result = json.loads(await f.read())

		# Check if we should use the original Mind2Web evaluation
		if use_mind2web:
			logger.info(f'Task {task_folder.name}: Using original Online_Mind2Web evaluation')

			# If a Online_Mind2Web_evaluation is already saved, we can skip the eval
			if result.get('Online_Mind2Web_evaluation'):
				return result.get('Online_Mind2Web_evaluation')

			# Get the screenshot paths, task description, and action history
			screenshot_paths = result.get('screenshot_paths', [])
			task_description = result.get('task')
			action_history = result.get('action_history', [])

			# Use the retry wrapper for evaluation
			try:
				# Await the async function directly instead of using asyncio.run()
				eval_result = await Online_Mind2Web_eval_with_retry(
					task_description, action_history, screenshot_paths, model, score_threshold
				)

				if eval_result is None:
					raise Exception('Evaluation failed after all retries')

				messages, text, system_msg, record, key_points = eval_result

				# Final steps to get judgement - use async invoke directly
				judgement_response = await model.ainvoke(messages)
				judgement = judgement_response.completion

				if 'success' in judgement.lower().split('status:')[1]:  # This is the official criteria for success
					evaluation = {
						'task_id': task_folder.name,
						'judgement': judgement,
						'success': True,
						'error': None,
						'score': 1.0,
					}
				else:  # This is the official criteria for failure
					evaluation = {
						'task_id': task_folder.name,
						'judgement': judgement,
						'success': False,
						'error': None,
						'score': 0.0,
					}

				# Save the Online_Mind2Web_evaluation into the result.json file
				result['Online_Mind2Web_evaluation'] = evaluation
				async with await anyio.open_file(result_file, 'w') as f:
					await f.write(json.dumps(result, indent=2))

				return evaluation

			except Exception as err:
				return {
					'task_id': task_folder.name,
					'judgement': f'Mind2Web evaluation failed: {type(err).__name__}: {err}',
					'success': False,
					'error': f'{type(err).__name__}: {err}',
					'score': 0.0,
				}

		else:
			# Use the new comprehensive judge system (default)
			logger.info(f'Task {task_folder.name}: Using comprehensive judge evaluation with {judge_repeat_count} repetition(s)')

			# Check if comprehensive judge result already exists
			if result.get('comprehensive_judge_evaluation'):
				existing_eval = result['comprehensive_judge_evaluation']
				return {
					'task_id': task_folder.name,
					'judgement': existing_eval.get('reasoning', 'Comprehensive evaluation completed'),
					'success': existing_eval.get('passed', False),
					'error': None,
					'score': existing_eval.get('final_score', 0) / 100.0,  # Convert to 0-1 scale
					'comprehensive_evaluation': existing_eval,
				}

			try:
				# Run comprehensive judge evaluation (with repeat and averaging handled in comprehensive_judge.py)
				comprehensive_result = await asyncio.wait_for(
					evaluate_task_with_comprehensive_judge(
						task_folder=task_folder, model=model, max_images=10, judge_repeat_count=judge_repeat_count
					),
					timeout=180 * judge_repeat_count,  # Increase timeout based on repeat count
				)

				if comprehensive_result.get('error'):
					return {
						'task_id': task_folder.name,
						'judgement': f'Comprehensive evaluation failed: {comprehensive_result["error"]}',
						'success': False,
						'error': comprehensive_result['error'],
						'score': 0.0,
					}

				comp_eval = comprehensive_result.get('comprehensive_judge')
				if comp_eval:
					return {
						'task_id': task_folder.name,
						'judgement': comp_eval.get('reasoning', 'Comprehensive evaluation completed'),
						'success': comp_eval.get('passed', False),
						'error': None,
						'score': comp_eval.get('final_score', 0) / 100.0,  # Convert to 0-1 scale
						'comprehensive_evaluation': comp_eval,
					}
				else:
					return {
						'task_id': task_folder.name,
						'judgement': 'Comprehensive judge failed to return results',
						'success': False,
						'error': 'Comprehensive judge failed to return results',
						'score': 0.0,
					}

			except Exception as err:
				logger.error(f'Comprehensive judge evaluation failed for {task_folder.name}: {err}')
				return {
					'task_id': task_folder.name,
					'judgement': f'Comprehensive judge error: {type(err).__name__}: {err}',
					'success': False,
					'error': f'Comprehensive judge error: {type(err).__name__}: {err}',
					'score': 0.0,
				}

	except Exception as err:
		return {
			'task_id': task_folder.name,
			'judgement': f'Evaluation failed: {type(err).__name__}: {err}',
			'success': False,
			'error': f'{type(err).__name__}: {err}',
			'score': 0.0,
		}


# ================================================
# Main Evaluation Functions
# ================================================


@observe(name='executor', span_type='EXECUTOR')  # type: ignore[arg-type]
async def run_agent_with_browser(
	browser_session: BrowserSession,
	task: Task,
	llm: BaseChatModel,
	max_steps: int,
	use_vision: bool,
	use_serp: bool = False,
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	use_thinking: bool = True,
	gmail_tokens_dict: dict[str, str] | None = None,
	images_per_step: int = 1,
) -> tuple[AgentHistoryList, str]:
	"""Run agent with the browser session"""
	# Create controller, optionally with SERP search, structured output, and Gmail 2FA support
	controller = create_controller(
		use_serp=use_serp, output_model=task.output_model, gmail_tokens_dict=gmail_tokens_dict, task=task
	)

	# Check for deprecated memory parameters
	if enable_memory:
		raise ValueError(
			'Memory support has been removed as of version 0.3.2. '
			'The agent context for memory is significantly improved and no longer requires the old memory system. '
			"Please remove the 'enable_memory' parameter."
		)

	# Set up login cookie monitoring if this is a login task
	is_login_task = hasattr(task, 'login_cookie') and task.login_cookie
	new_step_callback = None

	if is_login_task:
		logger.info(f'🔐 Setting up login cookie monitoring for task {task.task_id}')

		async def login_cookie_step_callback(browser_state_summary, agent_output, step_number):
			"""Callback to check login cookie after each step"""
			try:
				if task.login_cookie is not None:
					await check_login_cookie_at_step(
						browser_session=browser_session, task_id=task.task_id, login_cookie=task.login_cookie, step=step_number
					)
				else:
					logger.warning(f'❌ Task {task.task_id} Step {step_number}: login_cookie is None, skipping check')
			except Exception as e:
				logger.warning(f'❌ Error checking login cookie at step {step_number}: {type(e).__name__}: {e}')

		new_step_callback = login_cookie_step_callback

	agent = Agent(
		task=task.confirmed_task,
		llm=llm,
		controller=controller,
		browser_session=browser_session,
		use_vision=use_vision,
		max_actions_per_step=max_actions_per_step,
		validate_output=validate_output,
		planner_llm=planner_llm,
		planner_interval=planner_interval,
		use_thinking=use_thinking,
		images_per_step=images_per_step,
		source='eval_platform',
		calculate_cost=True,
		register_new_step_callback=new_step_callback,
	)

	# get last message
	await agent.run(max_steps=max_steps)
	last_input_messages = agent.message_manager.last_input_messages
	last_message = last_input_messages[-1].text

	# Save login cookie tracking if this was a login task
	if is_login_task:
		# Save tracking data to the task folder (will be created later in the pipeline)
		# For now, we'll save it when the task folder is available
		pass

	return agent.state.history, last_message


@observe(name='evaluate_task_result', span_type='EVALUATOR')  # type: ignore[arg-type]
async def evaluate_task_result(
	eval_model: BaseChatModel,
	task_folder: Path,
	task: Task | None = None,
	use_mind2web: bool = False,
	judge_repeat_count: int = 1,
) -> dict:
	"""Evaluate the task result"""
	# Check if this is a login task that should use both cookie-based and judge evaluation
	if task and hasattr(task, 'login_cookie') and task.login_cookie:
		logger.info(f'Using combined cookie-based and judge evaluation for login task {task.task_id}')

		# First run the judge evaluation to get comprehensive feedback
		judge_result = await judge_task_result(
			eval_model, task_folder, score_threshold=3, use_mind2web=use_mind2web, judge_repeat_count=judge_repeat_count
		)

		# Then run the cookie-based evaluation to get the actual score
		cookie_result = await evaluate_task_with_login_cookie(task.login_cookie, task_folder)

		# Use the score from cookie_result to overwrite judge_result
		judge_result['score'] = cookie_result['score']
		judge_result['success'] = cookie_result['success']
		judge_result['error'] = cookie_result['error']

		# Also overwrite comprehensive judge evaluation if it exists
		if 'comprehensive_evaluation' in judge_result and judge_result['comprehensive_evaluation']:
			judge_result['comprehensive_evaluation']['passed'] = cookie_result['success']
			# Convert score from 0-1 scale to 0-100 scale for comprehensive judge
			judge_result['comprehensive_evaluation']['final_score'] = int(cookie_result['score'] * 100)

		return judge_result
	else:
		return await judge_task_result(
			eval_model, task_folder, score_threshold=3, use_mind2web=use_mind2web, judge_repeat_count=judge_repeat_count
		)


@observe_debug()
async def cleanup_browser_safe(browser_session: BrowserSession):
	"""Safe browser cleanup with timeout"""
	try:
		logger.debug('Browser cleanup: Starting close operation for session')
		await asyncio.wait_for(browser_session.kill(), timeout=30)
		logger.debug('Browser cleanup: Close operation completed successfully')
	except TimeoutError:
		logger.warning('Browser cleanup: Timed out after 30 seconds')
	except Exception as e:
		logger.warning(f'Browser cleanup: Failed with error: {type(e).__name__}: {e}')


# ================================================
# Stage runner and related functions
# ================================================


def save_result_to_server(convex_url: str, secret_key: str, payload: dict) -> bool:
	"""Save result to server (sync function for use with asyncio.to_thread)"""
	return save_task_result_to_server(convex_url, secret_key, payload)


async def run_stage(stage: Stage, stage_func, timeout: int | None = None):
	"""Generic stage runner with timeout"""
	if timeout:
		return await asyncio.wait_for(stage_func(), timeout)
	return await stage_func()


def determine_current_stage(completed_stages: set) -> Stage:
	"""Determine current stage based on completed stages"""
	if Stage.SAVE_SERVER in completed_stages:
		return Stage.SAVE_SERVER
	elif Stage.EVALUATE in completed_stages:
		return Stage.EVALUATE
	elif Stage.FORMAT_HISTORY in completed_stages:
		return Stage.FORMAT_HISTORY
	elif Stage.RUN_AGENT in completed_stages:
		return Stage.RUN_AGENT
	elif Stage.SETUP_BROWSER in completed_stages:
		return Stage.SETUP_BROWSER
	else:
		return Stage.SETUP_BROWSER  # Default starting stage


@observe(name='evaluation', span_type='EVALUATION')  # type: ignore[arg-type]
async def run_task_with_semaphore(
	task: Task,
	run_id: str,
	lmnr_run_id: str | None,
	laminar_eval_link: str | None,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	llm: BaseChatModel,
	max_steps_per_task: int,
	headless: bool,
	use_vision: bool,
	semaphore_runs: asyncio.Semaphore,  # Pass semaphore as argument
	auth_distribution: dict | None = None,  # Pre-fetched auth distribution
	github_workflow_url: str | None = None,
	use_serp: bool = False,
	browser: str = 'local',
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	include_result: bool = False,
	highlight_elements: bool = True,
	use_mind2web_judge: bool = False,
	use_thinking: bool = True,
	gmail_tokens_dict: dict[str, str] | None = None,
	judge_repeat_count: int = 1,
	images_per_step: int = 1,
	default_navigation_timeout: int | None = None,
	default_timeout: int | None = None,
	minimum_wait_page_load_time: float | None = None,
	wait_for_network_idle_page_load_time: float | None = None,
	maximum_wait_page_load_time: float | None = None,
	wait_between_actions: float | None = None,
	stealth: bool = False,
) -> dict:
	"""Clean pipeline approach for running tasks"""
	task_start_time = time.time()
	logger.info(f'🚀 Task {task.task_id}: Starting execution pipeline')
	logger.info(f'📊 Task {task.task_id}: Waiting to acquire semaphore (current available: ~{semaphore_runs._value})')
	log_system_resources(f'TASK_START_{task.task_id}')

	semaphore_acquired_time = None
	async with semaphore_runs:
		semaphore_acquired_time = time.time()
		wait_time = semaphore_acquired_time - task_start_time
		logger.info(
			f'✅ Task {task.task_id}: Semaphore acquired after {wait_time:.2f}s (remaining slots: ~{semaphore_runs._value})'
		)
		log_system_resources(f'SEMAPHORE_ACQUIRED_{task.task_id}')

		task_result = None
		browser_session = None
		laminar_task_link = None
		datapoint_id = None
		agent_execution_time = None  # Track agent execution time separately

		try:
			if lmnr_run_id:
				try:
					datapoint_id = await laminar_client.evals.create_datapoint(
						eval_id=UUID(lmnr_run_id),
						data={
							'task_id': task.task_id,
							'confirmed_task': task.confirmed_task,
							'website': task.website,
							'reference_length': task.reference_length,
							'level': task.level,
							'cluster_id': task.cluster_id,
							'category': task.category,
						},
						metadata={
							'use_vision': str(use_vision),
							'use_serp': str(use_serp),
							'enable_memory': str(enable_memory),
							'memory_interval': str(memory_interval),
							'max_actions_per_step': str(max_actions_per_step),
							'validate_output': str(validate_output),
							'planner_model': str(planner_llm),
							'planner_interval': str(planner_interval),
							'include_result': str(include_result),
						},
						trace_id=Laminar.get_trace_id(),
					)
					# Only create task-specific link if we have the evaluation link
					if laminar_eval_link:
						laminar_task_link = f'{laminar_eval_link}?traceId={Laminar.get_trace_id()}&datapointId={datapoint_id}'
						logger.info(f'Task {task.task_id}: Laminar link: {laminar_task_link}')
					else:
						logger.debug(f'Task {task.task_id}: No Laminar evaluation link available, task link not created')
				except Exception as e:
					logger.warning(f'Task {task.task_id}: Failed to create Laminar datapoint: {type(e).__name__}: {e}')
			else:
				logger.debug(f'Task {task.task_id}: No Laminar run ID available, skipping datapoint creation')

				# Initialize task result and basic setup
			task_result = TaskResult(
				task.task_id, run_id, task.confirmed_task, task, max_steps_per_task, laminar_task_link, github_workflow_url
			)

			task_folder = Path(f'saved_trajectories/{task.task_id}')

			logger.info(f'Task {task.task_id}: Starting execution pipeline.')

			# Send initial progress update to show task is starting
			send_progress_update(convex_url, secret_key, run_id, task.task_id, 'starting', 'active', github_workflow_url)

			try:
				agent_history = None  # Initialize to track agent execution

				# Stage 1: Setup browser
				try:
					logger.info(f'Task {task.task_id}: Browser setup starting.')
					# Send progress update for starting browser setup
					send_progress_update(
						convex_url, secret_key, run_id, task.task_id, 'setup_browser', 'active', github_workflow_url
					)

					browser_session = await run_stage(
						Stage.SETUP_BROWSER,
						lambda: setup_browser_session(
							task,
							headless,
							highlight_elements,
							browser,
							default_navigation_timeout,
							default_timeout,
							minimum_wait_page_load_time,
							wait_for_network_idle_page_load_time,
							maximum_wait_page_load_time,
							wait_between_actions,
							stealth,
						),
						timeout=120,
					)
					task_result.stage_completed(Stage.SETUP_BROWSER)
					logger.info(f'Task {task.task_id}: Browser session started successfully.')

					# Send progress update for completed browser setup
					send_progress_update(
						convex_url, secret_key, run_id, task.task_id, 'browser_ready', 'active', github_workflow_url
					)
				except Exception as e:
					error = StageError(Stage.SETUP_BROWSER, 'exception', str(e))
					task_result.stage_failed(Stage.SETUP_BROWSER, error)
					logger.error(f'Task {task.task_id}: Browser setup failed: {str(e)}')
					# Send error progress update
					send_progress_update(
						convex_url, secret_key, run_id, task.task_id, 'setup_browser', 'failed', github_workflow_url, None, str(e)
					)
					# Continue to server save instead of early return

				# Stage 2: Run agent
				if browser_session:  # Only run agent if browser setup succeeded
					try:
						logger.info(f'Task {task.task_id}: Agent run starting.')
						# Send progress update for starting agent run
						send_progress_update(
							convex_url, secret_key, run_id, task.task_id, 'run_agent', 'active', github_workflow_url
						)

						# Handle auth information if task requires it
						task_with_auth = task
						if hasattr(task, 'auth_keys') and task.auth_keys:
							# Validate auth_keys is a list
							if isinstance(task.auth_keys, list) and len(task.auth_keys) > 0:
								if auth_distribution:
									logger.info(
										f'Task {task.task_id}: Using pre-fetched auth distribution for auth_keys: {task.auth_keys}'
									)
									auth_info_text = format_auth_info_for_agent(auth_distribution, task.auth_keys)
									if auth_info_text:
										# Create a modified task with auth info appended
										class TaskWithAuth(Task):
											def __init__(self, original_task: Task, auth_text: str):
												# Copy all attributes from original task
												for attr_name in dir(original_task):
													if not attr_name.startswith('__'):
														setattr(self, attr_name, getattr(original_task, attr_name))
												# Modify the confirmed_task to include auth info
												self.confirmed_task = original_task.confirmed_task + auth_text

										task_with_auth = TaskWithAuth(task, auth_info_text)
										logger.info(f'Task {task.task_id}: Auth info added to task description')
									else:
										logger.warning(
											f'Task {task.task_id}: No matching auth info found for keys: {task.auth_keys}'
										)
								else:
									logger.warning(f'Task {task.task_id}: Auth keys specified but no auth distribution available')
							else:
								logger.warning(f'Task {task.task_id}: auth_keys is not a valid list: {task.auth_keys}')

						# Start timing for agent execution only
						agent_start_time = time.time()

						agent_history, last_message = await run_stage(
							Stage.RUN_AGENT,
							lambda: run_agent_with_browser(
								browser_session,
								task_with_auth,
								llm,
								max_steps_per_task,
								use_vision,
								use_serp,
								enable_memory,
								memory_interval,
								max_actions_per_step,
								validate_output,
								planner_llm,
								planner_interval,
								use_thinking,
								gmail_tokens_dict,
								images_per_step,
							),
							timeout=1000,
						)

						# End timing for agent execution only
						agent_end_time = time.time()
						agent_execution_time = agent_end_time - agent_start_time

						task_result.stage_completed(Stage.RUN_AGENT)
						logger.info(f'Task {task.task_id}: Agent run completed in {agent_execution_time:.2f}s.')

						# Save login cookie tracking data if this was a login task
						if hasattr(task, 'login_cookie') and task.login_cookie:
							try:
								await save_login_cookie_tracking(task_folder, task.task_id)
							except Exception as e:
								logger.warning(
									f'Failed to save login cookie tracking for task {task.task_id}: {type(e).__name__}: {e}'
								)

						# Send progress update for completed agent run
						send_progress_update(
							convex_url, secret_key, run_id, task.task_id, 'agent_completed', 'active', github_workflow_url
						)
					except Exception as e:
						error = StageError(Stage.RUN_AGENT, 'exception', str(e))
						task_result.stage_failed(Stage.RUN_AGENT, error)
						logger.error(f'Task {task.task_id}: Agent run failed: {str(e) + " " + str(e.__traceback__)}')
						# Send error progress update
						send_progress_update(
							convex_url, secret_key, run_id, task.task_id, 'run_agent', 'failed', github_workflow_url, None, str(e)
						)

						# Continue to server save instead of early return

				# Stage 3: Format history (MOVED OUTSIDE browser_session block)
				if agent_history is not None:  # Only format if agent ran successfully
					try:
						logger.info(f'Task {task.task_id}: History formatting starting.')
						formatted_data = await run_stage(
							Stage.FORMAT_HISTORY,
							lambda: reformat_agent_history(
								agent_history,
								task.task_id,
								run_id,
								task.confirmed_task,
								last_message,
								include_result=include_result,
								agent_execution_time=agent_execution_time,  # Pass agent execution time
							),
						)
						task_result.stage_completed(Stage.FORMAT_HISTORY, formatted_data)
						logger.info(f'Task {task.task_id}: Agent history formatted.')
					except Exception as e:
						error = StageError(Stage.FORMAT_HISTORY, 'exception', str(e))
						task_result.stage_failed(Stage.FORMAT_HISTORY, error)
						logger.error(f'Task {task.task_id}: History formatting failed: {str(e)}')
						# Continue to server save instead of early return

				# Stage 4: Evaluate (MOVED OUTSIDE browser_session block)
				if task_result.has_execution_data() and Stage.EVALUATE not in task_result.completed_stages:
					try:
						logger.info(f'Task {task.task_id}: Evaluation starting.')
						evaluation = await run_stage(
							Stage.EVALUATE,
							lambda: evaluate_task_result(eval_model, task_folder, task, use_mind2web_judge, judge_repeat_count),
							timeout=300 * judge_repeat_count,  # Increase timeout based on repeat count
						)
						task_result.stage_completed(Stage.EVALUATE, evaluation)
						logger.info(f'Task {task.task_id}: Evaluation completed.')

						if lmnr_run_id and datapoint_id:
							await laminar_client.evals.update_datapoint(
								eval_id=UUID(lmnr_run_id),
								datapoint_id=datapoint_id,
								scores={
									'accuracy': evaluation['score'],
								},
							)
					except Exception as e:
						error = StageError(Stage.EVALUATE, 'exception', str(e))
						task_result.stage_failed(Stage.EVALUATE, error)
						logger.error(f'Task {task.task_id}: Evaluation failed: {str(e)}')

				# Stage 5: Save to server (MOVED OUTSIDE browser_session block - ALWAYS attempt)
				try:
					logger.info(f'Task {task.task_id}: Saving result to server.')
					# Only save to server if URLs are provided (skip for single task mode)
					if convex_url and secret_key:
						await run_stage(
							Stage.SAVE_SERVER,
							lambda: asyncio.to_thread(
								save_result_to_server,
								convex_url,
								secret_key,
								task_result.server_payload if task_result else {},
							),
							timeout=60,
						)
						task_result.stage_completed(Stage.SAVE_SERVER)
						logger.info(f'Task {task.task_id}: Successfully saved result to server.')
					else:
						# Single task mode - skip server save but mark as completed
						logger.info(f'Task {task.task_id}: Skipping server save (single task mode)')
						task_result.stage_completed(Stage.SAVE_SERVER)
				except Exception as e:
					error = StageError(Stage.SAVE_SERVER, 'exception', str(e))
					task_result.stage_failed(Stage.SAVE_SERVER, error)
					task_result.mark_server_save_failed(str(e))
					logger.error(f'Task {task.task_id}: Server save failed: {str(e)}')

			except TimeoutError:
				current_stage = determine_current_stage(task_result.completed_stages)
				error = StageError(current_stage, 'timeout', 'Operation timed out')
				task_result.stage_failed(current_stage, error)
				logger.error(f'Task {task.task_id}: {current_stage.value} timed out')

				# Attempt to save result even if timeout occurred
				try:
					logger.info(f'Task {task.task_id}: Attempting server save after timeout.')
					await run_stage(
						Stage.SAVE_SERVER,
						lambda: asyncio.to_thread(
							save_result_to_server, convex_url, secret_key, task_result.server_payload if task_result else {}
						),
						timeout=30,  # Shorter timeout for emergency save
					)
					task_result.stage_completed(Stage.SAVE_SERVER)
				except Exception as save_e:
					task_result.mark_server_save_failed(str(save_e))
					logger.error(f'Task {task.task_id}: Emergency server save after timeout failed: {str(save_e)}')

			except asyncio.CancelledError:
				task_result.mark_cancelled()
				logger.warning(f'Task {task.task_id}: Task was cancelled')

				# Attempt to save result even if cancelled
				try:
					logger.info(f'Task {task.task_id}: Attempting server save after cancellation.')
					await run_stage(
						Stage.SAVE_SERVER,
						lambda: asyncio.to_thread(
							save_result_to_server, convex_url, secret_key, task_result.server_payload if task_result else {}
						),
						timeout=30,  # Shorter timeout for emergency save
					)
					task_result.stage_completed(Stage.SAVE_SERVER)
				except Exception as save_e:
					task_result.mark_server_save_failed(str(save_e))
					logger.error(f'Task {task.task_id}: Emergency server save after cancellation failed: {str(save_e)}')

			except Exception as e:
				task_result.mark_critical_error(str(e))
				logger.critical(f'Task {task.task_id}: Critical error: {str(e)}', exc_info=True)

				# Attempt to save result even if critical error occurred
				try:
					logger.info(f'Task {task.task_id}: Attempting server save after critical error.')
					await run_stage(
						Stage.SAVE_SERVER,
						lambda: asyncio.to_thread(
							save_result_to_server, convex_url, secret_key, task_result.server_payload if task_result else {}
						),
						timeout=30,  # Shorter timeout for emergency save
					)
					task_result.stage_completed(Stage.SAVE_SERVER)
				except Exception as save_e:
					task_result.mark_server_save_failed(str(save_e))
					logger.error(f'Task {task.task_id}: Emergency server save after critical error failed: {str(save_e)}')

		except Exception as init_error:
			# Handle catastrophic initialization errors
			logger.critical(f'Task {task.task_id}: Catastrophic initialization error: {str(init_error)}', exc_info=True)
			if task_result is None:
				# Create minimal task result for server reporting
				try:
					task_result = TaskResult(
						task.task_id,
						run_id,
						task.confirmed_task,
						task,
						max_steps_per_task,
						laminar_task_link,
						github_workflow_url,
					)
					task_result.mark_critical_error(f'Initialization failed: {str(init_error)}')
				except Exception as result_error:
					logger.critical(f'Task {task.task_id}: Cannot create TaskResult: {str(result_error)}')
					# Return minimal error status as last resort
					return {
						'task_id': task.task_id,
						'success': False,
						'error': f'Catastrophic initialization failure: {str(init_error)}',
					}

			# Try emergency server save
			try:
				logger.info(f'Task {task.task_id}: Attempting emergency server save after initialization error.')
				await asyncio.to_thread(
					save_result_to_server, convex_url, secret_key, task_result.server_payload if task_result else {}
				)
			except Exception as save_e:
				logger.error(f'Task {task.task_id}: Emergency server save after initialization error failed: {str(save_e)}')

		finally:
			# Always cleanup browser if it was created
			if browser_session:
				logger.info(f'Task {task.task_id}: Starting browser cleanup')
				await cleanup_browser_safe(browser_session)
				logger.info(f'Task {task.task_id}: Browser cleanup completed')
			else:
				logger.info(f'Task {task.task_id}: No browser to cleanup')

		task_end_time = time.time()
		total_task_time = task_end_time - task_start_time
		semaphore_hold_time = task_end_time - (semaphore_acquired_time or task_start_time)

		# Log both pipeline time and agent execution time
		if agent_execution_time is not None:
			logger.info(
				f'🏁 Task {task.task_id}: Agent executed in {agent_execution_time:.2f}s (total pipeline: {total_task_time:.2f}s, semaphore held: {semaphore_hold_time:.2f}s)'
			)
		else:
			logger.info(
				f'🏁 Task {task.task_id}: Pipeline completed in {total_task_time:.2f}s (agent did not run, semaphore held: {semaphore_hold_time:.2f}s)'
			)

		logger.info(f'📊 Task {task.task_id}: About to release semaphore (remaining slots will be: ~{semaphore_runs._value + 1})')
		log_system_resources(f'TASK_END_{task.task_id}')

		final_result = (
			task_result.get_local_status()
			if task_result
			else {'task_id': task.task_id, 'success': False, 'error': 'Task result not available'}
		)

		logger.info(
			f'🎯 Task {task.task_id}: Final status - Success: {final_result.get("success", False)}, Error: {final_result.get("error", "None")}'
		)
		return final_result


@observe_debug()
async def run_multiple_tasks(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	lmnr_run_id: str | None,
	laminar_eval_link: str | None,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	auth_distribution: dict | None = None,
	github_workflow_url: str | None = None,
	max_parallel_runs: int = 3,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	use_serp: bool = False,
	browser: str = 'local',
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	include_result: bool = False,
	highlight_elements: bool = True,
	use_mind2web_judge: bool = False,
	use_thinking: bool = True,
	gmail_tokens_dict: dict[str, str] | None = None,
	judge_repeat_count: int = 1,
	images_per_step: int = 1,
	default_navigation_timeout: int | None = None,
	default_timeout: int | None = None,
	minimum_wait_page_load_time: float | None = None,
	wait_for_network_idle_page_load_time: float | None = None,
	maximum_wait_page_load_time: float | None = None,
	wait_between_actions: float | None = None,
	stealth: bool = False,
) -> dict:
	"""
	Run multiple tasks in parallel and evaluate results.
	"""
	batch_start_time = time.time()
	logger.info(f'🚀 BATCH START: Creating semaphore with max_parallel_runs={max_parallel_runs}')
	log_system_resources('BATCH_START')

	semaphore_runs = asyncio.Semaphore(max_parallel_runs)
	tasks_to_run = tasks[start_index:end_index] if end_index else tasks[start_index:]

	logger.info(f'📊 Starting {len(tasks_to_run)} tasks with parallel limit of {max_parallel_runs}')
	logger.info(f'📋 Task range: {start_index} to {end_index or len(tasks)} (total tasks available: {len(tasks)})')

	# Start resource monitoring
	await start_resource_monitoring(interval=30)

	# Setup signal handlers for graceful shutdown
	setup_signal_handlers()

	# Create a heartbeat task for long-running operations
	heartbeat_task = None
	heartbeat_stop_event = asyncio.Event()

	@observe_debug()
	async def heartbeat_logger():
		"""Log periodic heartbeat to show the process is alive"""
		heartbeat_count = 0
		while not heartbeat_stop_event.is_set():
			try:
				await asyncio.wait_for(heartbeat_stop_event.wait(), timeout=60.0)  # 1-minute heartbeat
				break  # Event was set, exit
			except TimeoutError:
				heartbeat_count += 1
				elapsed = time.time() - batch_start_time
				logger.info(f'💓 HEARTBEAT {heartbeat_count}: Batch still running after {elapsed:.1f}s')
				log_system_resources('HEARTBEAT')

				# Check for potential issues
				resources = get_system_resources()
				if resources['memory_percent'] > 90:
					logger.critical(f'🚨 CRITICAL: Memory usage at {resources["memory_percent"]:.1f}% - potential OOM risk!')
				if resources['chrome_process_count'] > 50:
					logger.warning(f'⚠️ HIGH BROWSER PROCESS COUNT: {resources["chrome_process_count"]} Chrome processes')

	try:
		# Start heartbeat logging
		heartbeat_task = asyncio.create_task(heartbeat_logger())
		logger.info('💓 Heartbeat monitoring started')

		# Run all tasks in parallel with additional parameters
		logger.info(f'🚀 Launching {len(tasks_to_run)} parallel task executions...')

		task_results = await asyncio.gather(
			*(
				run_task_with_semaphore(
					task=task,
					run_id=run_id,
					lmnr_run_id=lmnr_run_id,
					laminar_eval_link=laminar_eval_link,
					convex_url=convex_url,
					secret_key=secret_key,
					eval_model=eval_model,
					llm=llm,  # Pass the agent LLM
					max_steps_per_task=max_steps_per_task,
					headless=headless,
					use_vision=use_vision,
					semaphore_runs=semaphore_runs,  # Pass the semaphore
					auth_distribution=auth_distribution,  # Pass the pre-fetched auth distribution
					github_workflow_url=github_workflow_url,
					use_serp=use_serp,
					browser=browser,
					enable_memory=enable_memory,
					memory_interval=memory_interval,
					max_actions_per_step=max_actions_per_step,
					validate_output=validate_output,
					planner_llm=planner_llm,
					planner_interval=planner_interval,
					include_result=include_result,
					highlight_elements=highlight_elements,
					use_mind2web_judge=use_mind2web_judge,
					use_thinking=use_thinking,
					gmail_tokens_dict=gmail_tokens_dict,
					judge_repeat_count=judge_repeat_count,
					images_per_step=images_per_step,
					default_navigation_timeout=default_navigation_timeout,
					default_timeout=default_timeout,
					minimum_wait_page_load_time=minimum_wait_page_load_time,
					wait_for_network_idle_page_load_time=wait_for_network_idle_page_load_time,
					maximum_wait_page_load_time=maximum_wait_page_load_time,
					wait_between_actions=wait_between_actions,
					stealth=stealth,
				)
				for task in tasks_to_run
			),
			return_exceptions=True,  # Prevent task cancellation cascade
		)

		logger.info(f'✅ All {len(tasks_to_run)} parallel task executions completed')

	except Exception as e:
		logger.critical(f'🚨 CRITICAL ERROR in batch execution: {type(e).__name__}: {e}', exc_info=True)
		log_system_resources('BATCH_ERROR')
		# Create error results for all tasks
		task_results = [
			{'task_id': task.task_id, 'success': False, 'error': f'Batch execution failed: {str(e)}'} for task in tasks_to_run
		]

	finally:
		# Cleanup: Stop heartbeat and resource monitoring
		batch_end_time = time.time()
		total_batch_time = batch_end_time - batch_start_time
		logger.info(f'🏁 BATCH END: Total execution time {total_batch_time:.2f}s')

		if heartbeat_task and not heartbeat_task.done():
			heartbeat_stop_event.set()
			try:
				await asyncio.wait_for(heartbeat_task, timeout=5.0)
			except TimeoutError:
				logger.warning('Heartbeat task did not stop gracefully')
				heartbeat_task.cancel()

		await stop_resource_monitoring()

		log_system_resources('BATCH_CLEANUP')

	# Process task results and handle any exceptions returned by gather
	processed_results = []
	successful_tasks = 0
	failed_tasks = 0

	for i, result in enumerate(task_results):
		if isinstance(result, Exception):
			logger.error(f'❌ Task {i} failed with exception: {type(result).__name__}: {result}')
			task_id = tasks_to_run[i].task_id if i < len(tasks_to_run) else f'unknown_task_{i}'
			processed_results.append({'task_id': task_id, 'success': False, 'error': str(result)})
			failed_tasks += 1
		else:
			processed_results.append(result)
			if isinstance(result, dict) and result.get('success', False):
				successful_tasks += 1
			else:
				failed_tasks += 1

	logger.info(f'📊 FINAL RESULTS: {len(tasks_to_run)} tasks completed. Success: {successful_tasks}, Failed: {failed_tasks}')
	logger.info(f'📈 Success rate: {successful_tasks / len(tasks_to_run) * 100:.1f}%')

	logger.info('📋 All tasks completed.')

	return {'task_results': processed_results}


# ================================================
# Main Evaluation Pipeline
# ================================================


@observe_debug()
async def run_evaluation_pipeline(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	test_case: str,
	user_message: str,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	auth_distribution: dict | None = None,
	github_workflow_url: str | None = None,
	max_parallel_runs: int = 3,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	use_serp: bool = False,
	browser: str = 'local',
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	include_result: bool = False,
	laminar_eval_id: str | None = None,
	highlight_elements: bool = True,
	use_mind2web_judge: bool = False,
	use_thinking: bool = True,
	gmail_tokens_dict: dict[str, str] | None = None,
	judge_repeat_count: int = 1,
	images_per_step: int = 1,
	default_navigation_timeout: int | None = None,
	default_timeout: int | None = None,
	minimum_wait_page_load_time: float | None = None,
	wait_for_network_idle_page_load_time: float | None = None,
	maximum_wait_page_load_time: float | None = None,
	wait_between_actions: float | None = None,
	stealth: bool = False,
) -> dict:
	"""
	Complete evaluation pipeline that handles Laminar setup and task execution in the same event loop
	"""
	# --- Use provided Laminar Evaluation ID or skip tracking ---
	lmnr_run_id = None
	laminar_eval_link = None

	if laminar_eval_id:
		# Use existing evaluation ID provided from frontend
		lmnr_run_id = laminar_eval_id
		project_id = 'f07da4a9-b7de-488a-91e3-e17c5f6d676a'
		laminar_eval_link = f'https://www.lmnr.ai/project/{project_id}/evaluations/{lmnr_run_id}'
		logger.info(f'📊 Using provided Laminar evaluation ID: {lmnr_run_id}')
		logger.info(f'📊 Laminar evaluation link: {laminar_eval_link}')
	else:
		# No Laminar evaluation ID provided, skip tracking
		logger.info('📊 No Laminar evaluation ID provided, skipping Laminar tracking')
	# -------------------------

	# Update run data with Laminar link
	# run_data_update = {'laminarEvalLink': laminar_eval_link}
	# TODO: Update the run data on the server with the Laminar link if needed

	# Run the tasks
	return await run_multiple_tasks(
		tasks=tasks,
		llm=llm,
		run_id=run_id,
		lmnr_run_id=lmnr_run_id,
		laminar_eval_link=laminar_eval_link,
		convex_url=convex_url,
		secret_key=secret_key,
		eval_model=eval_model,
		auth_distribution=auth_distribution,
		github_workflow_url=github_workflow_url,
		max_parallel_runs=max_parallel_runs,
		max_steps_per_task=max_steps_per_task,
		start_index=start_index,
		end_index=end_index,
		headless=headless,
		use_vision=use_vision,
		use_serp=use_serp,
		browser=browser,
		enable_memory=enable_memory,
		memory_interval=memory_interval,
		max_actions_per_step=max_actions_per_step,
		validate_output=validate_output,
		planner_llm=planner_llm,
		planner_interval=planner_interval,
		include_result=include_result,
		highlight_elements=highlight_elements,
		use_mind2web_judge=use_mind2web_judge,
		use_thinking=use_thinking,
		gmail_tokens_dict=gmail_tokens_dict,
		judge_repeat_count=judge_repeat_count,
		images_per_step=images_per_step,
		default_navigation_timeout=default_navigation_timeout,
		default_timeout=default_timeout,
		minimum_wait_page_load_time=minimum_wait_page_load_time,
		wait_for_network_idle_page_load_time=wait_for_network_idle_page_load_time,
		maximum_wait_page_load_time=maximum_wait_page_load_time,
		wait_between_actions=wait_between_actions,
		stealth=stealth,
	)


# ================================================
# Main Evaluation Pipeline Execution
# ================================================


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Run and evaluate browser automation tasks')
	parser.add_argument('--parallel-runs', type=int, default=3, help='Number of parallel tasks to run')
	parser.add_argument('--max-steps', type=int, default=25, help='Maximum steps per task')
	parser.add_argument('--start', type=int, default=0, help='Start index')
	parser.add_argument('--end', type=int, default=None, help='End index (exclusive)')
	parser.add_argument('--headless', action='store_true', help='Run in headless mode')

	parser.add_argument(
		'--model', type=str, default='gpt-4o', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for the agent'
	)
	parser.add_argument(
		'--eval-model', type=str, default='gpt-4.1', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for evaluation'
	)
	parser.add_argument('--no-vision', action='store_true', help='Disable vision capabilities in the agent')

	parser.add_argument('--user-message', type=str, default='', help='User message to include in the run')
	parser.add_argument('--eval-group', type=str, default='', help='Evaluation group to include in the run')
	parser.add_argument('--developer-id', type=str, default=None, help='Name of the developer starting the run')
	parser.add_argument('--use-serp', action='store_true', help='Use SERP search instead of Google search')
	parser.add_argument(
		'--browser',
		type=str,
		default='local',
		help='Browser to use: local, anchor-browser, brightdata, browserbase, hyperbrowser, browser-use (default: local)',
	)
	parser.add_argument('--enable-memory', action='store_true', help='Enable mem0 memory system for agents')
	parser.add_argument('--memory-interval', type=int, default=10, help='Memory creation interval (default: 10 steps)')
	parser.add_argument('--max-actions-per-step', type=int, default=10, help='Maximum number of actions per step (default: 10)')
	parser.add_argument('--validate-output', action='store_true', help='Enable output validation using LLM')
	parser.add_argument(
		'--planner-model',
		type=str,
		default=None,
		choices=list(SUPPORTED_MODELS.keys()),
		help='Model to use for planning (separate from main agent model)',
	)
	parser.add_argument('--planner-interval', type=int, default=1, help='Run planner every N steps (default: 1)')
	parser.add_argument(
		'--judge-repeat-count',
		type=int,
		default=1,
		help='Number of times to repeat the judge evaluation for each task (averages over multiple judgments)',
	)
	parser.add_argument(
		'--images-per-step',
		type=int,
		default=1,
		help='Number of screenshots to include per step (1=current only, 2=current+previous, etc.)',
	)
	parser.add_argument(
		'--test-case', type=str, default='OnlineMind2Web', help='Name of the test case to fetch (default: OnlineMind2Web)'
	)
	parser.add_argument(
		'--run-id',
		type=str,
		default=None,
		help='Existing run ID to continue adding results to (if not provided, a new run will be started)',
	)
	parser.add_argument(
		'--include-result',
		action='store_true',
		help='Include result flag (functionality to be implemented)',
	)
	parser.add_argument(
		'--no-highlight-elements',
		action='store_false',
		dest='highlight_elements',
		default=True,
		help='Disable highlighting of interactive elements on the page (highlighting is enabled by default)',
	)
	parser.add_argument(
		'--laminar-eval-id',
		type=str,
		default=None,
		help='Existing Laminar evaluation ID to use (if not provided, a new evaluation will be created)',
	)
	parser.add_argument('--use-mind2web-judge', action='store_true', help='Use original judge')
	parser.add_argument('--no-thinking', action='store_true', help='Disable thinking in agent system prompt')
	parser.add_argument('--github-workflow-url', type=str, default=None, help='GitHub workflow URL for tracking')

	# Browser timeout and stealth configuration arguments
	parser.add_argument('--default-navigation-timeout', type=int, default=None, help='Default navigation timeout in milliseconds')
	parser.add_argument('--default-timeout', type=int, default=None, help='Default timeout in milliseconds')
	parser.add_argument(
		'--minimum-wait-page-load-time', type=float, default=None, help='Minimum wait time for page load in seconds'
	)
	parser.add_argument(
		'--wait-for-network-idle-page-load-time', type=float, default=None, help='Wait time for network idle page load in seconds'
	)
	parser.add_argument(
		'--maximum-wait-page-load-time', type=float, default=None, help='Maximum wait time for page load in seconds'
	)
	parser.add_argument('--wait-between-actions', type=float, default=None, help='Wait time between actions in seconds')
	parser.add_argument('--stealth', action='store_true', help='Enable stealth mode for browser')

	# Gmail 2FA support arguments
	parser.add_argument(
		'--gmail-2fa-tokens',
		type=str,
		default=None,
		help='JSON dictionary of user IDs to access tokens for Gmail 2FA (e.g., \'{"user123": "token1", "user456": "token2"}\')',
	)

	# Single task mode arguments
	parser.add_argument('--task-text', type=str, default=None, help='Task description for single task mode')
	parser.add_argument('--task-website', type=str, default=None, help='Task website for single task mode')
	# Keep task-id for backward compatibility but make it optional
	parser.add_argument('--task-id', type=str, default=None, help='Optional task ID (auto-generated if not provided)')

	args = parser.parse_args()

	# Set up logging - Make sure logger is configured before use in fetch function
	logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
	logger = logging.getLogger(__name__)  # Define logger for the module

	logger.info('Running tasks...')

	# Parse Gmail 2FA tokens - handle GitHub Actions raw object format
	gmail_tokens_dict = None
	if args.gmail_2fa_tokens:
		raw_tokens = args.gmail_2fa_tokens
		logger.info(f'🔧 Raw Gmail 2FA tokens received: "{raw_tokens}"')

		# Check if GitHub Actions passed us something like "[object Object]" or similar
		if raw_tokens in ['[object Object]', 'null', '', '{}']:
			logger.info('🔧 GitHub Actions passed placeholder value, no Gmail tokens available')
			gmail_tokens_dict = None
		else:
			try:
				# First try parsing as valid JSON (in case it's already proper JSON)
				gmail_tokens_dict = json.loads(raw_tokens)
				logger.info(f'🔧 Successfully parsed as JSON - Gmail 2FA tokens count: {len(gmail_tokens_dict)}')
				logger.info(f'🔧 Gmail 2FA users: {list(gmail_tokens_dict.keys())}')
			except json.JSONDecodeError:
				# If JSON parsing fails, try to parse GitHub Actions malformed toJSON format
				try:
					logger.info('🔧 JSON parsing failed, attempting to parse GitHub Actions malformed format...')

					# Handle GitHub Actions toJSON format: { key: value, key2: value2 }
					if raw_tokens.strip() and raw_tokens.strip() not in ['null', '{}']:
						# Remove outer braces and parse line by line
						content = raw_tokens.strip().strip('{}').strip()

						if content:
							tokens = {}
							lines = [line.strip() for line in content.split('\n') if line.strip()]

							for line in lines:
								# Remove trailing comma if present
								line = line.rstrip(',')

								if ':' in line:
									# Split on first colon only
									key, value = line.split(':', 1)
									key = key.strip()
									value = value.strip()

									# Store the key-value pair
									tokens[key] = value

							if tokens:
								gmail_tokens_dict = tokens
								logger.info('🔧 Successfully parsed malformed GitHub Actions format')
								logger.info(f'🔧 Gmail 2FA tokens count: {len(gmail_tokens_dict)}')
								logger.info(f'🔧 Gmail 2FA users: {list(gmail_tokens_dict.keys())}')
							else:
								logger.warning('🔧 No tokens found in malformed format')
								gmail_tokens_dict = None
						else:
							logger.warning('🔧 Empty content in malformed format')
							gmail_tokens_dict = None
					else:
						logger.info('🔧 Raw tokens empty or null')
						gmail_tokens_dict = None
				except Exception as e:
					logger.error(f'🔧 Failed to parse malformed GitHub Actions format: {type(e).__name__}: {e}')
					gmail_tokens_dict = None
	else:
		logger.info('🔧 Gmail 2FA tokens: None or empty')
	# Run tasks and evaluate
	load_dotenv()

	# --- Load Environment Variables (Always) ---
	CONVEX_URL = os.getenv('EVALUATION_TOOL_URL') or ''
	SECRET_KEY = os.getenv('EVALUATION_TOOL_SECRET_KEY') or ''

	# --- Load Tasks (Either Single Task or from Server) ---
	tasks = []
	task_id = None  # Initialize for proper scoping
	auth_distribution = None  # Initialize auth distribution

	# Check if this is single task mode
	if args.task_text:
		# Generate task ID if not provided
		task_id = args.task_id or f'single_task_{int(time.time())}_{hash(args.task_text) % 10000}'
		logger.info(f'Single task mode: Running task {task_id}')

		# Create a single task
		single_task = Task(
			task_id=task_id,
			confirmed_task=args.task_text,
			website=args.task_website,  # Optional website
		)
		tasks = [single_task]
		logger.info(f'Single task mode: Created task {task_id}')

	else:
		# Original multi-task mode - fetch from server
		if not CONVEX_URL or not SECRET_KEY:
			logger.error('Error: EVALUATION_TOOL_URL or EVALUATION_TOOL_SECRET_KEY environment variables not set.')
			exit(1)  # Exit if config is missing

		logger.info(f"Attempting to fetch task list '{args.test_case}' from server...")
		fetched_task_data = fetch_tasks_from_server(CONVEX_URL, SECRET_KEY, args.test_case)

		if fetched_task_data is None:
			logger.error('Failed to fetch tasks from the server. Exiting.')
			exit(1)  # Exit if fetch fails

		try:
			tasks = [Task(**task_data) for task_data in fetched_task_data]
			logger.info(f'Successfully loaded {len(tasks)} tasks from the server.')
		except (TypeError, ValueError) as e:
			logger.error(
				f'Error creating Task objects from fetched data. Ensure the data structure includes required fields (task_id, confirmed_task). Known optional fields: website, reference_length, level, cluster_id, login_cookie, login_type, category, auth_keys. Any additional fields will be accepted dynamically. Error: {type(e).__name__}: {e}'
			)
			logger.error(f'First item in fetched data: {fetched_task_data[0] if fetched_task_data else "None"}')
			exit(1)

	# --- Fetch Auth Distribution Once (if any tasks need auth) ---
	tasks_with_auth = [
		task
		for task in tasks
		if hasattr(task, 'auth_keys') and task.auth_keys and isinstance(task.auth_keys, list) and len(task.auth_keys) > 0
	]
	if tasks_with_auth and CONVEX_URL and SECRET_KEY:
		logger.info(f'Found {len(tasks_with_auth)} tasks requiring auth. Fetching auth distribution...')
		auth_distribution = fetch_auth_distribution_from_server(CONVEX_URL, SECRET_KEY)
		if auth_distribution:
			logger.info(
				f'Successfully fetched auth distribution with login info for: {list(auth_distribution.get("loginInfo", {}).keys())}'
			)
		else:
			logger.warning('Failed to fetch auth distribution. Tasks requiring auth may fail.')
	elif tasks_with_auth:
		logger.warning(f'Found {len(tasks_with_auth)} tasks requiring auth but no server config available')
	# -----------------------------

	# --- Start Run on Server (with optional existing Run ID) ---
	if args.run_id:
		logger.info(f'Initializing existing run ID: {args.run_id} with git info...')
	else:
		logger.info('Attempting to start a new run on the server...')

	# Get git info
	git_info = get_git_info()

	# Collect additional data from args to store with the run
	additional_run_data = {
		'max_steps': args.max_steps,
		'parallel_runs': args.parallel_runs,
		'start_index': args.start,
		'end_index': args.end,
		'headless': args.headless,
		'use_vision': not args.no_vision,
		'task_source': args.test_case,
		'llm_judge': args.eval_model,
		'use_serp': args.use_serp,
		'enable_memory': args.enable_memory,
		'memory_interval': args.memory_interval,
		'max_actions_per_step': args.max_actions_per_step,
		'validate_output': args.validate_output,
		'planner_model': args.planner_model,
		'planner_interval': args.planner_interval,
		'include_result': args.include_result,
		'judge_repeat_count': args.judge_repeat_count,
		'images_per_step': args.images_per_step,
		'default_navigation_timeout': args.default_navigation_timeout,
		'default_timeout': args.default_timeout,
		'minimum_wait_page_load_time': args.minimum_wait_page_load_time,
		'wait_for_network_idle_page_load_time': args.wait_for_network_idle_page_load_time,
		'maximum_wait_page_load_time': args.maximum_wait_page_load_time,
		'wait_between_actions': args.wait_between_actions,
		'stealth': args.stealth,
	}

	run_data = {
		'model': args.model,
		'gitBranch': git_info['branch'],
		'gitCommitHash': git_info['hash'],
		'gitCommitTimestamp': git_info['timestamp'],
		'gitRepo': git_info['repo'],
		'userMessage': args.user_message,
		'evalGroup': args.eval_group,
		'developerId': args.developer_id,
		'totalTasks': 1 if args.task_text else (len(tasks) - args.start if args.end is None else args.end - args.start),
		'testCaseName': args.test_case,
		'additionalData': additional_run_data,
		'laminarEvalLink': None,  # Will be updated after evaluation creation
	}

	# For single task mode, use provided run ID if available, otherwise skip server run creation
	if args.task_text:
		# Single task mode - use provided run_id (from GitHub Actions) or generate local one
		if args.run_id:
			run_id = args.run_id
			logger.info(f'Single task mode: Using provided run ID {run_id}')
		else:
			# Fallback for local single task runs without server
			safe_task_id = task_id or 'unknown'
			run_id = f'local_single_task_{safe_task_id}_{int(time.time())}'
			logger.info(f'Single task mode: Using local run ID {run_id}')
	else:
		# Multi-task mode - use server
		run_id = start_new_run(CONVEX_URL, SECRET_KEY, run_data, existing_run_id=args.run_id)

		if not run_id:
			logger.error('Failed to start/initialize run on the server. Exiting.')
			exit(1)

	logger.info(f'Successfully obtained run ID: {run_id}. Proceeding with tasks...')

	# Log search mode being used
	if args.use_serp:
		if SERPER_API_KEY:
			logger.info('🔍 Using SERP search (Serper API) instead of Google search')
		else:
			logger.warning('⚠️ --use-serp flag provided but SERPER_API_KEY not set. Search will fail!')
	else:
		logger.info('🔍 Using default Google search')

	# Log browser mode being used
	if args.browser == 'anchor-browser':
		if ANCHOR_BROWSER_API_KEY:
			logger.info('🌐 Using Anchor Browser (remote browser service)')
		else:
			logger.warning('⚠️ --browser anchor-browser provided but ANCHOR_BROWSER_API_KEY not set. Will use local browser!')
	elif args.browser == 'brightdata':
		if BRIGHTDATA_CDP_URL:
			logger.info('🌐 Using Brightdata browser (remote browser service)')
		else:
			logger.warning('⚠️ --browser brightdata provided but BRIGHTDATA_CDP_URL not set. Will use local browser!')
	elif args.browser == 'browserbase':
		if BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID:
			logger.info('🌐 Using Browserbase (remote browser service)')
		else:
			logger.warning(
				'⚠️ --browser browserbase provided but BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set. Will use local browser!'
			)
	elif args.browser == 'hyperbrowser':
		if HYPERBROWSER_API_KEY:
			logger.info('🌐 Using Hyperbrowser (remote browser service)')
		else:
			logger.warning('⚠️ --browser hyperbrowser provided but HYPERBROWSER_API_KEY not set. Will use local browser!')
	elif args.browser == 'browser-use':
		logger.warning('🌐 Browser-use not implemented yet. Will use local browser!')
	else:
		logger.info('🌐 Using local browser')

	# Log memory configuration
	if args.enable_memory:
		logger.info(f'🧠 Memory enabled: mem0 system with interval={args.memory_interval} steps')
	else:
		logger.info('🧠 Memory disabled')

	# Log other agent configuration
	logger.info(f'🎯 Max actions per step: {args.max_actions_per_step}')

	if args.validate_output:
		logger.info('✅ Output validation enabled')
	else:
		logger.info('✅ Output validation disabled')

	if args.planner_model:
		logger.info(f'🗺️ Planner enabled: {args.planner_model} (interval={args.planner_interval} steps)')
	else:
		logger.info('🗺️ Planner disabled')
	# -------------------------

	# --- Get LLMs ---
	logger.info(f'Instantiating agent LLM: {args.model}')
	try:
		# Get the selected LLM for the agent
		llm = get_llm(args.model)
		logger.info('Agent LLM instantiated successfully.')
	except Exception as e:
		logger.error(f'Failed to instantiate agent LLM ({args.model}): {type(e).__name__}: {e}', exc_info=True)
		exit(1)

	logger.info(f'Instantiating evaluation LLM: {args.eval_model}')
	try:
		eval_model = get_llm(args.eval_model)
		logger.info(f'Evaluation LLM ({args.eval_model}) instantiated successfully.')
	except Exception as e:
		logger.error(
			f'Failed to instantiate evaluation LLM ({args.eval_model}): {type(e).__name__}: {e}. Make sure required API keys are set.',
			exc_info=True,
		)
		exit(1)

	# Get planner LLM if specified
	planner_llm = None
	if args.planner_model:
		logger.info(f'Instantiating planner LLM: {args.planner_model}')
		try:
			planner_llm = get_llm(args.planner_model)
			logger.info(f'Planner LLM ({args.planner_model}) instantiated successfully.')
		except Exception as e:
			logger.error(
				f'Failed to instantiate planner LLM ({args.planner_model}): {type(e).__name__}: {e}. Make sure required API keys are set.',
				exc_info=True,
			)
			exit(1)
	# -----------------

	# Log initial system state
	logger.info('🔧 EVALUATION STARTUP')
	log_system_resources('STARTUP')

	# For single task mode, set appropriate start/end indices and parallel runs
	if args.task_text:
		# Single task mode - force single execution but SAVE results to server
		start_index = 0
		end_index = 1
		parallel_runs = 1
		# Use server URLs for single task mode too so results are saved and visible
		convex_url = CONVEX_URL if CONVEX_URL else ''
		secret_key = SECRET_KEY if SECRET_KEY else ''
		logger.info('Single task mode: Running single task with parallel_runs=1')
	else:
		# Multi-task mode - use provided arguments
		start_index = args.start
		end_index = args.end
		parallel_runs = args.parallel_runs
		convex_url = CONVEX_URL
		secret_key = SECRET_KEY

	try:
		results = asyncio.run(
			run_evaluation_pipeline(
				tasks=tasks,
				llm=llm,
				run_id=run_id,
				test_case=args.test_case,
				user_message=args.user_message,
				convex_url=convex_url,
				secret_key=secret_key,
				eval_model=eval_model,
				auth_distribution=auth_distribution,
				github_workflow_url=args.github_workflow_url,
				max_parallel_runs=parallel_runs,
				max_steps_per_task=args.max_steps,
				start_index=start_index,
				end_index=end_index,
				headless=args.headless,
				use_vision=not args.no_vision,
				use_serp=args.use_serp,
				browser=args.browser,
				enable_memory=args.enable_memory,
				memory_interval=args.memory_interval,
				max_actions_per_step=args.max_actions_per_step,
				validate_output=args.validate_output,
				planner_llm=planner_llm,
				planner_interval=args.planner_interval,
				include_result=args.include_result,
				laminar_eval_id=args.laminar_eval_id,
				highlight_elements=args.highlight_elements,
				use_mind2web_judge=args.use_mind2web_judge,
				use_thinking=not args.no_thinking,
				gmail_tokens_dict=gmail_tokens_dict,
				judge_repeat_count=args.judge_repeat_count,
				images_per_step=args.images_per_step,
				default_navigation_timeout=args.default_navigation_timeout,
				default_timeout=args.default_timeout,
				minimum_wait_page_load_time=args.minimum_wait_page_load_time,
				wait_for_network_idle_page_load_time=args.wait_for_network_idle_page_load_time,
				maximum_wait_page_load_time=args.maximum_wait_page_load_time,
				wait_between_actions=args.wait_between_actions,
				stealth=args.stealth,
			)
		)

		logger.info('✅ EVALUATION COMPLETED SUCCESSFULLY')
		log_system_resources('SUCCESS_COMPLETION')

	except KeyboardInterrupt:
		logger.warning('⚠️ EVALUATION INTERRUPTED by user (Ctrl+C)')
		log_system_resources('INTERRUPTED')
		raise
	except Exception as e:
		logger.critical(f'🚨 EVALUATION FAILED: {type(e).__name__}: {e}', exc_info=True)
		log_system_resources('FAILED_COMPLETION')
		raise

	logger.info('✅ All tasks completed successfully.')
