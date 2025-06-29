# pyright: reportMissingImports=false
# ==============================================================================================================
# Documentation for this evaluation file.

# Here is the command to run the evaluation:
# python eval/service.py --parallel-runs 2 --max-steps 25 --start 0 --end 100 --model llama-4-maverick --eval-model gpt-4.1 --no-vision --eval-group "PRTests" --user-message "message here"

# ==============================================================================================================


# ==============================================================================================================
# This is the LLM as a judge evaluation system from the OSU-NLP Group paper
# Any adaptiations made should be explicitly stated here:
# Adaptations:
# We are using our own wrapper for the OpenAI API
# This means we changed model.generate to model.invoke. The behavior of the model should be identical.
# Added a Online_Mind2Web_eval_with_retry wrapper with retry logic in case of API rate limiting or other issues.


# @article{xue2025illusionprogressassessingcurrent,
#       title={An Illusion of Progress? Assessing the Current State of Web Agents},
#       author={Tianci Xue and Weijian Qi and Tianneng Shi and Chan Hee Song and Boyu Gou and Dawn Song and Huan Sun and Yu Su},
#       year={2025},
#       eprint={2504.01382},
#       archivePrefix={arXiv},
#       primaryClass={cs.AI},
#       url={https://arxiv.org/abs/2504.01382},
# }

# @inproceedings{deng2023mind2web,
#  author = {Deng, Xiang and Gu, Yu and Zheng, Boyuan and Chen, Shijie and Stevens, Sam and Wang, Boshi and Sun, Huan and Su, Yu},
#  booktitle = {Advances in Neural Information Processing Systems},
#  editor = {A. Oh and T. Naumann and A. Globerson and K. Saenko and M. Hardt and S. Levine},
#  pages = {28091--28114},
#  publisher = {Curran Associates, Inc.},
#  title = {Mind2Web: Towards a Generalist Agent for the Web},
#  url = {https://proceedings.neurips.cc/paper_files/paper/2023/file/5950bf290a1570ea401bf98882128160-Paper-Datasets_and_Benchmarks.pdf},
#  volume = {36},
#  year = {2023}
# }
# ==============================================================================================================
import asyncio
import base64
import gc
import io
import logging
import re
import signal
import sys
import threading
import time
from uuid import UUID

import anyio
import psutil
from lmnr import AsyncLaminarClient, Laminar, observe
from PIL import Image
from pydantic import BaseModel

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.base import BaseChatModel
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI

MAX_IMAGE = 5


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s: %(message)s')
logger = logging.getLogger(__name__)

Laminar.initialize()
laminar_client = AsyncLaminarClient()

# Global variables for resource monitoring
_resource_monitor_task = None
_resource_monitor_stop_event = None
_graceful_shutdown_initiated = False


def get_system_resources():
	"""Get current system resource usage"""
	try:
		# Memory usage
		memory = psutil.virtual_memory()
		memory_percent = memory.percent
		memory_available_gb = memory.available / (1024**3)

		# CPU usage
		cpu_percent = psutil.cpu_percent(interval=1)

		# Load average (Unix only)
		try:
			load_avg = psutil.getloadavg()
			load_1min = load_avg[0]
		except (AttributeError, OSError):
			load_1min = 0.0

		# Process count
		process_count = len(psutil.pids())

		# Chrome/Browser processes
		chrome_processes = []
		python_processes = []
		for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'cpu_percent']):
			try:
				name = proc.info['name'].lower()
				if 'chrome' in name or 'chromium' in name:
					chrome_processes.append(proc.info)
				elif 'python' in name:
					python_processes.append(proc.info)
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				continue

		return {
			'memory_percent': memory_percent,
			'memory_available_gb': memory_available_gb,
			'cpu_percent': cpu_percent,
			'load_1min': load_1min,
			'process_count': process_count,
			'chrome_process_count': len(chrome_processes),
			'python_process_count': len(python_processes),
			'chrome_processes': chrome_processes[:5],  # Top 5 chrome processes
			'python_processes': python_processes[:5],  # Top 5 python processes
		}
	except Exception as e:
		logger.warning(f'Failed to get system resources: {type(e).__name__}: {e}')
		return {
			'memory_percent': 0,
			'memory_available_gb': 0,
			'cpu_percent': 0,
			'load_1min': 0,
			'process_count': 0,
			'chrome_process_count': 0,
			'python_process_count': 0,
			'chrome_processes': [],
			'python_processes': [],
		}


def log_system_resources(context: str = ''):
	"""Log current system resource usage"""
	resources = get_system_resources()
	logger.info(f'=== SYSTEM RESOURCES {context} ===')
	logger.info(f'Memory: {resources["memory_percent"]:.1f}% used, {resources["memory_available_gb"]:.2f}GB available')
	logger.info(f'CPU: {resources["cpu_percent"]:.1f}%, Load: {resources["load_1min"]:.2f}')
	logger.info(
		f'Processes: {resources["process_count"]} total, {resources["chrome_process_count"]} Chrome, {resources["python_process_count"]} Python'
	)

	if resources['chrome_processes']:
		logger.info('Top Chrome processes:')
		for proc in resources['chrome_processes']:
			logger.info(
				f'  PID {proc["pid"]}: {proc["name"]} - CPU: {proc["cpu_percent"]:.1f}%, Memory: {proc["memory_percent"]:.1f}%'
			)

	logger.info('=' * (20 + len(context)))


async def start_resource_monitoring(interval: int = 30):
	"""Start background resource monitoring"""
	global _resource_monitor_task, _resource_monitor_stop_event

	if _resource_monitor_task is not None:
		logger.warning('Resource monitoring is already running')
		return

	_resource_monitor_stop_event = asyncio.Event()

	async def monitor_loop():
		"""Background monitoring loop"""
		logger.info(f'Starting resource monitoring (interval: {interval}s)')
		try:
			while _resource_monitor_stop_event is not None and not _resource_monitor_stop_event.is_set():
				try:
					log_system_resources('MONITOR')

					# Check for concerning resource levels
					resources = get_system_resources()
					if resources['memory_percent'] > 85:
						logger.warning(f'⚠️ HIGH MEMORY USAGE: {resources["memory_percent"]:.1f}%')
					if resources['cpu_percent'] > 90:
						logger.warning(f'⚠️ HIGH CPU USAGE: {resources["cpu_percent"]:.1f}%')
					if resources['chrome_process_count'] > 20:
						logger.warning(f'⚠️ HIGH CHROME PROCESS COUNT: {resources["chrome_process_count"]}')

					# Force garbage collection periodically
					if resources['memory_percent'] > 70:
						logger.info('Running garbage collection due to high memory usage')
						gc.collect()

				except Exception as e:
					logger.error(f'Error in resource monitoring: {type(e).__name__}: {e}')

				try:
					if _resource_monitor_stop_event is not None:
						await asyncio.wait_for(_resource_monitor_stop_event.wait(), timeout=interval)
					else:
						await asyncio.sleep(interval)
					break  # Event was set, exit loop
				except TimeoutError:
					continue  # Timeout reached, continue monitoring
		except Exception as e:
			logger.error(f'Resource monitoring loop crashed: {type(e).__name__}: {e}')
		finally:
			logger.info('Resource monitoring stopped')

	_resource_monitor_task = asyncio.create_task(monitor_loop())


async def stop_resource_monitoring():
	"""Stop background resource monitoring"""
	global _resource_monitor_task, _resource_monitor_stop_event

	if _resource_monitor_stop_event is not None:
		_resource_monitor_stop_event.set()

	if _resource_monitor_task is not None:
		try:
			await asyncio.wait_for(_resource_monitor_task, timeout=5.0)
		except TimeoutError:
			logger.warning('Resource monitoring task did not stop gracefully')
			_resource_monitor_task.cancel()
			try:
				await _resource_monitor_task
			except asyncio.CancelledError:
				pass

		_resource_monitor_task = None
		_resource_monitor_stop_event = None


def setup_signal_handlers():
	"""Setup signal handlers for graceful shutdown"""
	global _graceful_shutdown_initiated

	def signal_handler(signum, frame):
		global _graceful_shutdown_initiated
		if _graceful_shutdown_initiated:
			logger.critical('🔥 FORCE EXIT: Second signal received, terminating immediately')
			sys.exit(1)

		_graceful_shutdown_initiated = True
		logger.warning(f'⚠️ GRACEFUL SHUTDOWN: Received signal {signum}, initiating graceful shutdown...')
		log_system_resources('SHUTDOWN')

		# Try to stop resource monitoring
		try:
			loop = asyncio.get_event_loop()
			if loop.is_running():
				loop.create_task(stop_resource_monitoring())
		except Exception as e:
			logger.error(f'Failed to stop resource monitoring during shutdown: {e}')

		# Give some time for cleanup, then force exit
		def force_exit():
			time.sleep(10)
			if _graceful_shutdown_initiated:
				logger.critical('🔥 FORCE EXIT: Graceful shutdown timeout, terminating')
				sys.exit(1)

		threading.Thread(target=force_exit, daemon=True).start()

	# Register signal handlers
	signal.signal(signal.SIGINT, signal_handler)
	signal.signal(signal.SIGTERM, signal_handler)


def encode_image(image):
	"""Convert a PIL image to base64 string."""
	if image.mode == 'RGBA':
		image = image.convert('RGB')
	buffered = io.BytesIO()
	image.save(buffered, format='JPEG')
	return base64.b64encode(buffered.getvalue()).decode('utf-8')


async def identify_key_points(task, model):
	system_msg = """You are an expert tasked with analyzing a given task to identify the key points explicitly stated in the task description.

**Objective**: Carefully analyze the task description and extract the critical elements explicitly mentioned in the task for achieving its goal.

**Instructions**:
1. Read the task description carefully.
2. Identify and extract **key points** directly stated in the task description.
   - A **key point** is a critical element, condition, or step explicitly mentioned in the task description.
   - Do not infer or add any unstated elements.
   - Words such as "best," "highest," "cheapest," "latest," "most recent," "lowest," "closest," "highest-rated," "largest," and "newest" must go through the sort function(e.g., the key point should be "Filter by highest").

**Respond with**:
- **Key Points**: A numbered list of the explicit key points for completing this task, one per line, without explanations or additional details."""
	prompt = """Task: {task}"""
	text = prompt.format(task=task)
	messages = [
		{'role': 'system', 'content': system_msg},
		{
			'role': 'user',
			'content': [{'type': 'text', 'text': text}],
		},
	]
	response = await model.ainvoke(messages)
	return response.completion


async def judge_image(task, image_path, key_points, model):
	system_msg = """You are an expert evaluator tasked with determining whether an image contains information about the necessary steps to complete a task.

**Objective**: Analyze the provided image and decide if it shows essential steps or evidence required for completing the task. Use your reasoning to explain your decision before assigning a score.

**Instructions**:
1. Provide a detailed description of the image, including its contents, visible elements, text (if any), and any notable features.

2. Carefully examine the image and evaluate whether it contains necessary steps or evidence crucial to task completion:  
- Identify key points that could be relevant to task completion, such as actions, progress indicators, tool usage, applied filters, or step-by-step instructions.  
- Does the image show actions, progress indicators, or critical information directly related to completing the task?  
- Is this information indispensable for understanding or ensuring task success?
- If the image contains partial but relevant information, consider its usefulness rather than dismissing it outright.

3. Provide your response in the following format:  
- **Reasoning**: Explain your thought process and observations. Mention specific elements in the image that indicate necessary steps, evidence, or lack thereof.  
- **Score**: Assign a score based on the reasoning, using the following scale:  
    - **1**: The image does not contain any necessary steps or relevant information.  
    - **2**: The image contains minimal or ambiguous information, unlikely to be essential.  
    - **3**: The image includes some relevant steps or hints but lacks clarity or completeness.  
    - **4**: The image contains important steps or evidence that are highly relevant but not fully comprehensive.  
    - **5**: The image clearly displays necessary steps or evidence crucial for completing the task.

Respond with:  
1. **Reasoning**: [Your explanation]  
2. **Score**: [1-5]"""

	jpg_base64_str = encode_image(Image.open(image_path))

	prompt = """**Task**: {task}

**Key Points for Task Completion**: {key_points}

The snapshot of the web page is shown in the image."""
	text = prompt.format(task=task, key_points=key_points)

	messages = [
		{'role': 'system', 'content': system_msg},
		{
			'role': 'user',
			'content': [
				{'type': 'text', 'text': text},
				{
					'type': 'image_url',
					'image_url': {'url': f'data:image/jpeg;base64,{jpg_base64_str}', 'detail': 'high'},
				},
			],
		},
	]
	response = await model.ainvoke(messages)
	return response.completion


async def Online_Mind2Web_eval(task, last_actions, images_path, model, score_threshold):
	system_msg = """You are an expert in evaluating the performance of a web navigation agent. The agent is designed to help a human user navigate a website to complete a task. Given the user's task, the agent's action history, key points for task completion, some potentially important web pages in the agent's trajectory and their reasons, your goal is to determine whether the agent has completed the task and achieved all requirements.

Your response must strictly follow the following evaluation criteria!
*Important Evaluation Criteria*:
1: The filtered results must be displayed correctly. If filters were not properly applied (i.e., missing selection, missing confirmation, or no visible effect in results), the task is not considered successful.
2: You must carefully check whether these snapshots and action history meet these key points. Ensure that specific filter conditions, such as "best," "highest," "cheapest," "latest," "most recent," "lowest," "closest," "highest-rated," "largest," and "newest" are correctly applied using the filter function(e.g., sort function).
3: Certain key points or requirements should be applied by the filter. Otherwise, a search with all requirements as input will be deemed a failure since it cannot guarantee that all results meet the requirements!
4: If the task requires filtering by a specific range of money, years, or the number of beds and bathrooms, the applied filter must exactly match the given requirement. Any deviation results in failure. To ensure the task is successful, the applied filter must precisely match the specified range without being too broad or too narrow.
Examples of Failure Cases:
- If the requirement is less than $50, but the applied filter is less than $25, it is a failure.
- If the requirement is $1500-$2500, but the applied filter is $2000-$2500, it is a failure.
- If the requirement is $25-$200, but the applied filter is $0-$200, it is a failure.
- If the required years are 2004-2012, but the filter applied is 2001-2012, it is a failure.
- If the required years are before 2015, but the applied filter is 2000-2014, it is a failure.
- If the task requires exactly 2 beds, but the filter applied is 2+ beds, it is a failure.
5: Some tasks require a submission action or a display of results to be considered successful.
6: If the retrieved information is invalid or empty(e.g., No match was found), but the agent has correctly performed the required action, it should still be considered successful.
7: If the current page already displays all available items, then applying a filter is not necessary. As long as the agent selects items that meet the requirements (e.g., the cheapest or lowest price), the task is still considered successful.

*IMPORTANT*
Format your response into two lines as shown below:

Thoughts: <your thoughts and reasoning process based on double-checking each key points and the evaluation criteria>
Status: "success" or "failure"
"""
	prompt = """User Task: {task}

Key Points: {key_points}

Action History:
{last_actions}

The potentially important snapshots of the webpage in the agent's trajectory and their reasons:
{thoughts}"""

	key_points = await identify_key_points(task, model)
	key_points = key_points.replace('\n\n', '\n')

	try:
		key_points = key_points.split('**Key Points**:')[1]
		key_points = '\n'.join(line.lstrip() for line in key_points.splitlines())
	except IndexError:
		key_points = key_points.split('Key Points:')[-1]
		key_points = '\n'.join(line.lstrip() for line in key_points.splitlines())

	tasks = [judge_image(task, image_path, key_points, model) for image_path in images_path]
	image_responses = await asyncio.gather(*tasks)

	whole_content_img = []
	whole_thoughts = []
	record = []
	pattern = r'[1-5]'
	for response, image_path in zip(image_responses, images_path):
		try:
			score_text = response.split('Score')[1]
			thought = response.split('**Reasoning**:')[-1].strip().lstrip('\n').split('\n\n')[0].replace('\n', ' ')
			score = re.findall(pattern, score_text)[0]
			record.append({'Response': response, 'Score': int(score)})
		except Exception as e:
			logger.error(f'Error processing response: {type(e).__name__}: {e}')
			score = 0
			record.append({'Response': response, 'Score': 0})

		if int(score) >= score_threshold:
			jpg_base64_str = encode_image(Image.open(image_path))
			whole_content_img.append(
				{'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{jpg_base64_str}', 'detail': 'high'}}
			)
			if thought != '':
				whole_thoughts.append(thought)

	whole_content_img = whole_content_img[:MAX_IMAGE]
	whole_thoughts = whole_thoughts[:MAX_IMAGE]
	if len(whole_content_img) == 0:
		prompt = """User Task: {task}

Key Points: {key_points}

Action History:
{last_actions}"""
	text = prompt.format(
		task=task,
		last_actions='\n'.join(f'{i + 1}. {action}' for i, action in enumerate(last_actions)),
		key_points=key_points,
		thoughts='\n'.join(f'{i + 1}. {thought}' for i, thought in enumerate(whole_thoughts)),
	)

	messages = [
		{'role': 'system', 'content': system_msg},
		{'role': 'user', 'content': [{'type': 'text', 'text': text}] + whole_content_img},
	]
	return messages, text, system_msg, record, key_points


async def Online_Mind2Web_eval_with_retry(task, last_actions, images_path, model, score_threshold, max_retries=3):
	"""
	Wrapper for Online_Mind2Web_eval with retry logic.

	Args:
	    task: The task description
	    last_actions: list of actions taken
	    images_path: list of image paths
	    model: The model to use for evaluation
	    score_threshold: Score threshold for image filtering
	    max_retries: Maximum number of retry attempts

	Returns:
	    Tuple of (messages, text, system_msg, record, key_points) or None if all retries fail
	"""
	for attempt in range(max_retries):
		try:
			return await Online_Mind2Web_eval(task, last_actions, images_path, model, score_threshold)
		except Exception as e:
			if attempt == max_retries - 1:  # Last attempt
				logger.error(f'Failed to evaluate after {max_retries} attempts. Error: {type(e).__name__}: {str(e)}')
				raise
			logger.warning(f'Attempt {attempt + 1} failed. Retrying... Error: {type(e).__name__}: {str(e)}')
			await asyncio.sleep(2**attempt)  # Exponential backoff


# ==============================================================================================================


# ==============================================================================================================
# A service for evaluating the performance of the agent
# ==============================================================================================================
import argparse
import http.client
import json
import os
import subprocess
from dataclasses import dataclass, field

# Define Stage enum and related classes for the pipeline
from enum import Enum
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Import the new comprehensive judge system (conditional import for backwards compatibility)
try:
	from judge_system import evaluate_task_with_comprehensive_judge

	COMPREHENSIVE_JUDGE_AVAILABLE = True
except ImportError:
	logger.warning('Comprehensive judge system not available. Only Mind2Web judge will be available.')
	COMPREHENSIVE_JUDGE_AVAILABLE = False

	async def evaluate_task_with_comprehensive_judge(*args, **kwargs) -> dict[str, Any]:
		"""Fallback function when comprehensive judge system is not available"""
		raise ImportError('Comprehensive judge system not available')


class Stage(Enum):
	SETUP_BROWSER = 'setup_browser'
	RUN_AGENT = 'run_agent'
	FORMAT_HISTORY = 'format_history'
	EVALUATE = 'evaluate'
	SAVE_SERVER = 'save_server'


@dataclass
class StageError:
	stage: Stage
	error_type: str
	message: str


@dataclass
class TaskResult:
	task_id: str
	run_id: str
	confirmed_task: str
	task: Any
	max_steps: int
	laminar_link: str | None = None
	completed_stages: set[Stage] = field(default_factory=set)
	stage_data: dict[Stage, Any] = field(default_factory=dict)
	errors: list = field(default_factory=list)
	cancelled: bool = False
	critical_error: str | None = None
	server_save_failed: bool = False

	def stage_completed(self, stage: Stage, data: Any = None):
		self.completed_stages.add(stage)
		if data is not None:
			self.stage_data[stage] = data

	def stage_failed(self, stage: Stage, error: StageError):
		self.errors.append(error)

	def mark_cancelled(self):
		self.cancelled = True

	def mark_critical_error(self, error: str):
		self.critical_error = error

	def mark_server_save_failed(self, error: str):
		self.server_save_failed = True
		self.errors.append(StageError(Stage.SAVE_SERVER, 'server_save', error))

	def has_execution_data(self) -> bool:
		return Stage.RUN_AGENT in self.completed_stages or Stage.FORMAT_HISTORY in self.completed_stages

	@property
	def server_payload(self) -> dict[str, Any]:
		"""Generate payload for server submission"""
		payload = {
			'taskId': self.task_id,
			'runId': self.run_id,
			'task': self.confirmed_task,
			'completed_stages': [stage.value for stage in self.completed_stages],
			'has_errors': len(self.errors) > 0,
			'cancelled': self.cancelled,
			'critical_error': self.critical_error,
			'server_save_failed': self.server_save_failed,
			'laminarTaskLink': self.laminar_link,
		}

		# Add task execution data if available
		if Stage.FORMAT_HISTORY in self.completed_stages:
			format_data = self.stage_data.get(Stage.FORMAT_HISTORY, {})
			payload.update(
				{
					'actionHistory': format_data.get('action_history', []),
					'finalResultResponse': format_data.get('final_result_response', ''),
					'selfReportCompleted': format_data.get('self_report_completed', False),
					'selfReportSuccess': format_data.get('self_report_success', False),
					'taskDuration': format_data.get('task_duration'),
					'steps': format_data.get('steps'),
					'maxSteps': self.max_steps,
					'tokensUsed': format_data.get('tokensUsed'),
					'completeHistory': format_data.get('complete_history', []),  # Add complete step history
				}
			)

		# Add evaluation data if available
		if Stage.EVALUATE in self.completed_stages:
			eval_data = self.stage_data.get(Stage.EVALUATE, {})

			# Handle comprehensive judge evaluation
			comp_eval = eval_data.get('comprehensive_evaluation') or eval_data.get('comprehensive_judge')
			if comp_eval:
				# Convert enum lists to string lists for database storage
				task_categories = comp_eval.get('task_categories', [])
				if task_categories and hasattr(task_categories[0], 'value'):
					task_categories = [cat.value for cat in task_categories]

				error_categories = comp_eval.get('error_categories', [])
				if error_categories and hasattr(error_categories[0], 'value'):
					error_categories = [err.value for err in error_categories]

				payload.update(
					{
						'comprehensiveJudgeEvaluationSummary': comp_eval.get('task_summary'),
						'comprehensiveJudgeEvaluationReasoning': comp_eval.get('reasoning'),
						'comprehensiveJudgeEvaluationPassed': comp_eval.get('passed'),
						'comprehensiveJudgeEvaluationScore': comp_eval.get('final_score'),
						'comprehensiveJudgeEvaluationCategories': task_categories,
						'comprehensiveJudgeEvaluationErrors': error_categories,
						'comprehensiveJudgeEvaluationTips': comp_eval.get('improvement_tips', []),
						'comprehensiveJudgeEvaluationCriticalIssues': comp_eval.get('critical_issues', []),
						'comprehensiveJudgeEvaluationScores': comp_eval.get('scores'),
						'comprehensiveJudgeEvaluationFull': comp_eval,  # Include full comprehensive eval data
					}
				)

			# Handle legacy Mind2Web evaluation (for compatibility)
			payload.update(
				{
					'onlineMind2WebEvaluationJudgement': eval_data.get('judgement') or 'No evaluation available',
					'onlineMind2WebEvaluationError': eval_data.get('error'),
					'onlineMind2WebEvaluationSuccess': eval_data.get('success', False),
					'onlineMind2WebEvaluationScore': eval_data.get('score', 0.0),
				}
			)

		# Ensure all data in payload is JSON serializable
		serialized_payload = make_json_serializable(payload)
		# Type assertion since we know payload is a dict and make_json_serializable preserves dict structure
		assert isinstance(serialized_payload, dict), 'Payload serialization should preserve dict structure'
		return serialized_payload

	def get_local_status(self) -> dict[str, Any]:
		"""Get local status summary"""
		success = (
			Stage.EVALUATE in self.completed_stages
			and not self.cancelled
			and self.critical_error is None
			and len([e for e in self.errors if e.error_type == 'exception']) == 0
		)
		return {
			'task_id': self.task_id,
			'success': success,
			'error': self.critical_error or (self.errors[0].message if self.errors else None),
			'completed_stages': [stage.value for stage in self.completed_stages],
		}


from browser_use import ActionResult, Agent, BrowserProfile, BrowserSession, Controller
from browser_use.agent.views import AgentHistoryList

SUPPORTED_MODELS = {
	# Anthropic
	'claude-3.5-sonnet': {
		'provider': 'anthropic',
		'model_name': 'claude-3-5-sonnet-20240620',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-3.5-sonnet-exp': {
		'provider': 'anthropic',
		'model_name': 'claude-3-5-sonnet-20241022',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-3.7-sonnet-exp': {
		'provider': 'anthropic',
		'model_name': 'claude-3-7-sonnet-20250219',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-sonnet-4': {
		'provider': 'anthropic',
		'model_name': 'claude-sonnet-4-20250514',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-opus-4': {
		'provider': 'anthropic',
		'model_name': 'claude-opus-4-20250514',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	# Deepseek (via OpenAI Compatible API)
	'deepseek-reasoner': {
		'provider': 'openai_compatible',
		'model_name': 'deepseek-reasoner',
		'base_url': 'https://api.deepseek.com/v1',
		'api_key_env': 'DEEPSEEK_API_KEY',
	},
	'deepseek-chat': {
		'provider': 'openai_compatible',
		'model_name': 'deepseek-chat',
		'base_url': 'https://api.deepseek.com/v1',
		'api_key_env': 'DEEPSEEK_API_KEY',
	},
	# Google
	'gemini-1.5-flash': {'provider': 'google', 'model_name': 'gemini-1.5-flash-latest', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.0-flash-lite': {'provider': 'google', 'model_name': 'gemini-2.0-flash-lite', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.0-flash': {'provider': 'google', 'model_name': 'gemini-2.0-flash', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.5-pro': {'provider': 'google', 'model_name': 'gemini-2.5-pro-preview-03-25', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.5-flash': {'provider': 'google', 'model_name': 'gemini-2.5-flash-latest', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.5-pro-preview-05-06': {
		'provider': 'google',
		'model_name': 'gemini-2.5-pro-preview-05-06',
		'api_key_env': 'GEMINI_API_KEY',
	},
	'gemini-2.5-flash-preview': {
		'provider': 'google',
		'model_name': 'gemini-2.5-flash-preview-04-17',
		'api_key_env': 'GEMINI_API_KEY',
	},
	# OpenAI
	'gpt-4.1': {'provider': 'openai', 'model_name': 'gpt-4.1-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4.1-mini': {'provider': 'openai', 'model_name': 'gpt-4.1-mini-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4.1-nano': {'provider': 'openai', 'model_name': 'gpt-4.1-nano-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o': {'provider': 'openai', 'model_name': 'gpt-4o', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o-mini': {'provider': 'openai', 'model_name': 'gpt-4o-mini', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-o4-mini': {'provider': 'openai', 'model_name': 'o4-mini', 'api_key_env': 'OPENAI_API_KEY'},
	# X.ai (via OpenAI Compatible API)
	'grok-2': {
		'provider': 'openai_compatible',
		'model_name': 'grok-2-1212',
		'base_url': 'https://api.x.ai/v1',
		'api_key_env': 'XAI_API_KEY',
	},
	'grok-3': {
		'provider': 'openai_compatible',
		'model_name': 'grok-3-beta',
		'base_url': 'https://api.x.ai/v1',
		'api_key_env': 'XAI_API_KEY',
	},
	# Groq
	'gemma2-9b-it': {
		'provider': 'openai_compatible',
		'model_name': 'gemma2-9b-it',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	'llama-3.3-70b-versatile': {
		'provider': 'openai_compatible',
		'model_name': 'llama-3.3-70b-versatile',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	'llama-3.1-8b-instant': {
		'provider': 'openai_compatible',
		'model_name': 'llama-3.1-8b-instant',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	'llama3-70b-8192': {
		'provider': 'openai_compatible',
		'model_name': 'llama3-70b-8192',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	'llama3-8b-8192': {
		'provider': 'openai_compatible',
		'model_name': 'llama3-8b-8192',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	# Groq Preview
	'llama-4-maverick': {
		'provider': 'openai_compatible',
		'model_name': 'meta-llama/llama-4-maverick-17b-128e-instruct',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	'llama-4-scout': {
		'provider': 'openai_compatible',
		'model_name': 'meta-llama/llama-4-scout-17b-16e-instruct',
		'base_url': 'https://api.groq.com/openai/v1',
		'api_key_env': 'GROQ_API_KEY',
	},
	# SambaNova
	'deepseek-r1-sambanova': {
		'provider': 'openai_compatible',
		'model_name': 'DeepSeek-R1',
		'base_url': 'https://api.sambanova.ai/v1',
		'api_key_env': 'SAMBANOVA_API_KEY',
	},
	'llama-4-maverick-sambanova': {
		'provider': 'openai_compatible',
		'model_name': 'Llama-4-Maverick-17B-128E-Instruct',
		'base_url': 'https://api.sambanova.ai/v1',
		'api_key_env': 'SAMBANOVA_API_KEY',
	},
}

# Check for SERPER API key
SERPER_API_KEY = os.getenv('SERPER_API_KEY')
if not SERPER_API_KEY:
	logger.warning('SERPER_API_KEY is not set. Search functionality will not be available.')


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


def create_controller(use_serp: bool = False, output_model: type[BaseModel] | None = None):
	"""Create a controller, optionally with SERP search"""
	if use_serp:
		return create_controller_with_serp_search(output_model=output_model)
	else:
		return Controller(output_model=output_model)


def get_llm(model_name: str):
	"""Instantiates the correct ChatModel based on the model name."""
	if model_name not in SUPPORTED_MODELS:
		raise ValueError(f'Unsupported model: {model_name}. Supported models are: {list(SUPPORTED_MODELS.keys())}')

	config = SUPPORTED_MODELS[model_name]
	provider = config['provider']
	api_key_env = config.get('api_key_env')
	api_key = os.getenv(api_key_env) if api_key_env else None

	if not api_key and api_key_env:
		logger.warning(
			f'API key environment variable {api_key_env} not found or empty for model {model_name}. Trying without API key if possible.'
		)
		api_key = None

	match provider:
		case 'openai':
			kwargs = {'model': config['model_name'], 'temperature': 0.0}
			# Must set temperatue=1 if model is gpt-o4-mini
			if model_name == 'gpt-o4-mini':
				kwargs['temperature'] = 1
			if api_key:
				kwargs['api_key'] = api_key
			return ChatOpenAI(**kwargs)
		case 'anthropic':
			kwargs = {
				'model': config['model_name'],
				'temperature': 0.0,
				'timeout': 100,
			}
			if api_key:
				kwargs['api_key'] = api_key
			return ChatAnthropic(**kwargs)
		case 'google':
			kwargs = {'model': config['model_name'], 'temperature': 0.0}
			if api_key:
				kwargs['api_key'] = api_key
			return ChatGoogle(**kwargs)
		case 'openai_compatible':
			kwargs = {'model': config['model_name'], 'base_url': config['base_url'], 'temperature': 0.0}
			if api_key:
				kwargs['api_key'] = api_key
			elif config.get('base_url'):
				logger.warning(
					f'API key for {model_name} at {config["base_url"]} is missing, but base_url is specified. Authentication may fail.'
				)
			return ChatOpenAI(**kwargs)
		case _:
			raise ValueError(f'Unknown provider: {provider}')


def clean_action_dict(action_dict: dict) -> dict:
	return {k: clean_action_dict(v) if isinstance(v, dict) else v for k, v in action_dict.items() if v is not None}


def make_json_serializable(obj: Any) -> Any:
	"""
	Convert objects to JSON-serializable types.
	Handles common non-serializable types like enums, custom objects, etc.
	"""
	if obj is None:
		return None
	elif isinstance(obj, (str, int, float, bool)):
		return obj
	elif isinstance(obj, dict):
		return {k: make_json_serializable(v) for k, v in obj.items()}
	elif isinstance(obj, (list, tuple)):
		return [make_json_serializable(item) for item in obj]
	elif hasattr(obj, 'value'):  # Handle enums
		return obj.value
	elif hasattr(obj, '__dict__'):  # Handle custom objects
		return str(obj)
	else:
		return str(obj)


async def reformat_agent_history(
	agent_history: AgentHistoryList,
	task_id: str,
	run_id: str,
	task: str,
	last_message: str,
	base_path: str = 'saved_trajectories',
	include_result: bool = False,
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

	# Calculate task duration from metadata
	task_duration = None
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
					task_duration = end_time_float - start_time_float
				except (ValueError, TypeError) as e:
					logger.warning(f'Could not calculate task duration due to invalid timestamp format: {e}')

	# Conditionally include the final result in action history
	if include_result and final_result and final_result.strip():
		action_history = action_history + [final_result]

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
	}

	# Save results file
	results_path = task_dir / 'result.json'
	async with await anyio.open_file(results_path, 'w') as f:
		# Use a custom JSON encoder to handle potential non-serializable types like Path
		await f.write(json.dumps(results, indent=2, default=str))

	return results


def create_pydantic_model_from_schema(schema: dict, model_name: str = 'DynamicModel') -> type[BaseModel]:
	"""
	Convert JSON schema to Pydantic model class using datamodel-code-generator.

	Args:
		schema: JSON schema dictionary
		model_name: Name for the generated model class

	Returns:
		Pydantic model class that can be used with Controller(output_model=...)

	Example:
		schema = {
			"type": "object",
			"properties": {
				"name": {"type": "string"},
				"age": {"type": "integer"},
				"email": {"type": "string"}
			},
			"required": ["name", "age"]
		}
		PersonModel = create_pydantic_model_from_schema(schema, "Person")
		controller = Controller(output_model=PersonModel)
	"""
	try:
		import importlib.util
		import tempfile
		from pathlib import Path

		from datamodel_code_generator import DataModelType, generate

		# Handle case where schema might be a string (JSON)
		if isinstance(schema, str):
			schema = json.loads(schema)

		logger.debug(f'Creating Pydantic model from schema: {schema}')

		# Initialize paths for cleanup
		schema_path = None
		model_path = None

		try:
			# Create temporary files for input schema and output model
			with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as schema_file:
				json.dump(schema, schema_file, indent=2)
				schema_path = Path(schema_file.name)

			with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as model_file:
				model_path = Path(model_file.name)

			# Generate Pydantic model code using datamodel-code-generator
			generate(
				input_=schema_path,
				output=model_path,
				output_model_type=DataModelType.PydanticV2BaseModel,
				class_name=model_name,
			)

			# Read the generated Python code
			generated_code = model_path.read_text()
			logger.debug(f'Generated Pydantic model code:\n{generated_code}')

			# Create a module and execute the generated code
			spec = importlib.util.spec_from_loader(f'dynamic_model_{model_name}', loader=None)
			if spec is None:
				raise ValueError('Failed to create module spec')

			module = importlib.util.module_from_spec(spec)

			# Add necessary imports to the module namespace before executing
			from typing import Any, Optional, Union

			from pydantic import BaseModel, Field

			module.__dict__.update(
				{
					'Optional': Optional,
					'Union': Union,
					'list': list,
					'dict': dict,
					'Any': Any,
					'BaseModel': BaseModel,
					'Field': Field,
					'str': str,
					'int': int,
					'float': float,
					'bool': bool,
				}
			)

			# Execute the generated code in the module's namespace
			exec(generated_code, module.__dict__)

			# Get the generated model class
			if hasattr(module, model_name):
				model_class = getattr(module, model_name)
				# Rebuild the model to resolve forward references and type annotations
				# Pass the module's namespace so it can resolve imports like Optional
				model_class.model_rebuild(_types_namespace=module.__dict__)
				logger.debug(f'Successfully created Pydantic model: {model_class}')
				return model_class
			else:
				# Fallback: look for any BaseModel subclass in the module
				for attr_name in dir(module):
					attr = getattr(module, attr_name)
					if isinstance(attr, type) and issubclass(attr, BaseModel) and attr != BaseModel:
						# Rebuild the model to resolve forward references and type annotations
						# Pass the module's namespace so it can resolve imports like Optional
						attr.model_rebuild(_types_namespace=module.__dict__)
						logger.debug(f'Using fallback model class: {attr}')
						return attr

				raise ValueError('No Pydantic model class found in generated code')

		finally:
			# Clean up temporary files safely
			if schema_path is not None:
				try:
					schema_path.unlink()
				except Exception as cleanup_error:
					logger.warning(f'Failed to cleanup schema file: {cleanup_error}')
			if model_path is not None:
				try:
					model_path.unlink()
				except Exception as cleanup_error:
					logger.warning(f'Failed to cleanup model file: {cleanup_error}')

	except ImportError as e:
		logger.error(f'datamodel-code-generator not available: {e}')
		logger.error('Falling back to basic schema conversion')

		try:
			# Fallback to basic implementation if datamodel-code-generator is not available
			from typing import Any, Optional

			from pydantic import create_model

			def json_type_to_python_type(json_type):
				"""Map JSON schema types to Python types"""
				# Handle union types (arrays of types)
				if isinstance(json_type, list):
					# Handle union types like ["string", "null"]
					types = []
					for t in json_type:
						if t == 'null':
							continue  # We'll handle null separately
						types.append(json_type_to_python_type(t))

					if len(types) == 0:
						return Any
					elif len(types) == 1:
						return types[0]
					else:
						# len(types) >= 2 - create Union dynamically
						from typing import Union

						# For 2 types, use Union[type1, type2]
						if len(types) == 2:
							return Union[types[0], types[1]]
						# For more types, we need to use a different approach
						# Since Union doesn't support unpacking, we'll just use the first type
						# This is a limitation of the fallback implementation
						return types[0]

				# Handle single types
				if json_type == 'string':
					return str
				elif json_type == 'integer':
					return int
				elif json_type == 'number':
					return float
				elif json_type == 'boolean':
					return bool
				elif json_type == 'array':
					return list[Any]
				elif json_type == 'object':
					return dict[str, Any]
				else:
					return Any

			# Handle case where schema might be a string (JSON)
			if isinstance(schema, str):
				schema = json.loads(schema)

			# Extract properties and required fields from schema
			properties = schema.get('properties', {})
			required_fields = schema.get('required', [])

			# Build field definitions for create_model
			field_definitions = {}

			for field_name, field_schema in properties.items():
				json_type = field_schema.get('type')
				field_type = json_type_to_python_type(json_type)

				# Check if the field allows null (either not required or explicitly allows null)
				allows_null = field_name not in required_fields or (isinstance(json_type, list) and 'null' in json_type)

				# Handle required vs optional fields
				if field_name in required_fields and not allows_null:
					field_definitions[field_name] = (field_type, ...)  # Required field
				else:
					optional_type = Optional[field_type]  # Use Optional instead of Union[T, None]
					field_definitions[field_name] = (optional_type, None)  # Optional field with default None

			# Create the dynamic model using create_model
			return create_model(model_name, **field_definitions)

		except Exception as fallback_error:
			logger.error(f'Fallback schema conversion also failed: {fallback_error}')
			raise ValueError(f'Both primary and fallback schema conversion failed: {fallback_error}') from fallback_error

	except Exception as e:
		logger.error(f'Failed to create Pydantic model from schema: {e}')
		logger.error(f'Schema: {schema}')
		raise ValueError(f'Invalid JSON schema: {e}') from e


class Task:
	def __init__(self, task_id, confirmed_task, **kwargs):
		# Validate required fields
		if not task_id:
			raise ValueError('task_id is required and cannot be empty')
		if not confirmed_task:
			raise ValueError('confirmed_task is required and cannot be empty')

		# Set required fields
		self.task_id = task_id
		self.confirmed_task = confirmed_task

		# Set optional fields dynamically
		# Known optional fields with defaults
		self.website = kwargs.get('website', None)
		self.reference_length = kwargs.get('reference_length', None)
		self.level = kwargs.get('level', None)
		self.cluster_id = kwargs.get('cluster_id', None)
		self.login_cookie = kwargs.get('login_cookie', None)
		self.login_type = kwargs.get('login_type', None)
		self.category = kwargs.get('category', None)
		self.output_schema = kwargs.get('output_schema', None)  # Add structured output schema support
		if self.output_schema:
			# Convert JSON schema to Pydantic model class
			self.output_model = create_pydantic_model_from_schema(self.output_schema, f'Task_{self.task_id}_Output')
		else:
			self.output_model = None

		# Store any additional optional fields
		known_fields = {
			'website',
			'reference_length',
			'level',
			'cluster_id',
			'login_cookie',
			'login_type',
			'category',
			'output_schema',
		}
		self.additional_fields = {k: v for k, v in kwargs.items() if k not in known_fields}

		# Make all additional fields accessible as attributes
		for key, value in self.additional_fields.items():
			setattr(self, key, value)

	def __str__(self):
		# Include main fields and indicate if there are additional fields
		base_str = f'Task(task_id={self.task_id}, confirmed_task={self.confirmed_task}, website={self.website}, reference_length={self.reference_length}, level={self.level}, cluster_id={self.cluster_id}, login_cookie={self.login_cookie}, login_type={self.login_type}, category={self.category}, output_schema={self.output_schema}'
		if self.additional_fields:
			additional_str = ', '.join(f'{k}={v}' for k, v in self.additional_fields.items())
			base_str += f', {additional_str}'
		base_str += ')'
		return base_str

	def __repr__(self):
		return self.__str__()


async def judge_task_result(model, task_folder: Path, score_threshold: float = 3, use_mind2web: bool = False) -> dict:
	"""
	Judge a single task result using the comprehensive judge system by default,
	with optional fallback to the original Online_Mind2Web evaluation.

	Args:
	    model: The model to use for evaluation
	    task_folder: Path to the task result folder
	    score_threshold: Score threshold for image filtering (used only for Mind2Web)
	    use_mind2web: If True, use the original Online_Mind2Web evaluation instead

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
			logger.info(f'Task {task_folder.name}: Using comprehensive judge evaluation')

			# Check if comprehensive judge is available
			if not COMPREHENSIVE_JUDGE_AVAILABLE:
				logger.warning(f'Task {task_folder.name}: Comprehensive judge not available, falling back to Mind2Web')
				return await judge_task_result(model, task_folder, score_threshold, use_mind2web=True)

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
				# Run comprehensive judge evaluation
				comprehensive_result = await evaluate_task_with_comprehensive_judge(
					task_folder=task_folder, model=model, max_images=10
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


async def run_stage(stage: Stage, stage_func, timeout: int | None = None):
	"""Generic stage runner with timeout"""
	if timeout:
		return await asyncio.wait_for(stage_func(), timeout)
	return await stage_func()


async def setup_browser_session(task: Task, headless: bool, highlight_elements: bool = True) -> BrowserSession:
	"""Setup browser session for the task"""
	logger.debug(f'Browser setup: Initializing BrowserSession for task {task.task_id}')

	# Use incognito mode (user_data_dir=None) for evaluations to avoid state pollution
	profile = BrowserProfile(
		user_data_dir=None,  # Incognito mode - no persistent state
		headless=headless,
		chromium_sandbox=False,  # running in docker
		highlight_elements=highlight_elements,  # Control element highlighting (passed to profile)
		keep_alive=True,
		# higher timeouts = higher success rates on long tail of slow sites or if on a slow CI server
		# timeout=60_000,
		# default_timeout=60_000,
		# default_navigation_timeout=60_000,
		# wait_for_network_idle_page_load_time=60.0,
		# maximum_wait_page_load_time=60.0,
		# wait_between_actions=0.5,
		# ignore_https_errors=True,  # some eval tasks have http:// or broken https sites in them
	)

	browser_session = BrowserSession(browser_profile=profile)

	# Start browser session
	logger.debug(f'Browser setup: Starting browser session for task {task.task_id}')
	await browser_session.start()
	logger.debug(f'Browser setup: Browser session started for task {task.task_id}')

	# Navigate to task starting url if provided
	if task.website:
		logger.debug(f'Browser setup: Navigating to {task.website} for task {task.task_id}')
		await browser_session.navigate(task.website)

	logger.debug(f'Browser setup: Setup completed for task {task.task_id}')
	return browser_session


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
) -> tuple[AgentHistoryList, str]:
	"""Run agent with the browser session"""
	# Create controller, optionally with SERP search and structured output
	controller = create_controller(use_serp=use_serp, output_model=task.output_model)

	# Check for deprecated memory parameters
	if enable_memory:
		raise ValueError(
			'Memory support has been removed as of version 0.3.2. '
			'The agent context for memory is significantly improved and no longer requires the old memory system. '
			"Please remove the 'enable_memory' parameter."
		)

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
		source='eval_platform',
	)
	# get last message
	await agent.run(max_steps=max_steps)
	last_input_messages = agent.message_manager.last_input_messages
	last_message = last_input_messages[-1].text
	return agent.state.history, last_message


@observe(name='evaluate_task_result', span_type='EVALUATOR')  # type: ignore[arg-type]
async def evaluate_task_result(eval_model: BaseChatModel, task_folder: Path, use_mind2web: bool = False) -> dict:
	"""Evaluate the task result"""
	return await judge_task_result(eval_model, task_folder, score_threshold=3, use_mind2web=use_mind2web)


def save_result_to_server(convex_url: str, secret_key: str, payload: dict) -> bool:
	"""Save result to server (sync function for use with asyncio.to_thread)"""
	return save_task_result_to_server(convex_url, secret_key, payload)


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
	use_serp: bool = False,
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	include_result: bool = False,
	highlight_elements: bool = True,
	use_mind2web_judge: bool = False,
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
			task_result = TaskResult(task.task_id, run_id, task.confirmed_task, task, max_steps_per_task, laminar_task_link)

			task_folder = Path(f'saved_trajectories/{task.task_id}')

			logger.info(f'Task {task.task_id}: Starting execution pipeline.')
			try:
				agent_history = None  # Initialize to track agent execution

				# Stage 1: Setup browser
				try:
					logger.info(f'Task {task.task_id}: Browser setup starting.')
					browser_session = await run_stage(
						Stage.SETUP_BROWSER, lambda: setup_browser_session(task, headless, highlight_elements), timeout=120
					)
					task_result.stage_completed(Stage.SETUP_BROWSER)
					logger.info(f'Task {task.task_id}: Browser session started successfully.')
				except Exception as e:
					error = StageError(Stage.SETUP_BROWSER, 'exception', str(e))
					task_result.stage_failed(Stage.SETUP_BROWSER, error)
					logger.error(f'Task {task.task_id}: Browser setup failed: {str(e)}')
					# Continue to server save instead of early return

				# Stage 2: Run agent
				if browser_session:  # Only run agent if browser setup succeeded
					try:
						logger.info(f'Task {task.task_id}: Agent run starting.')

						agent_history, last_message = await run_stage(
							Stage.RUN_AGENT,
							lambda: run_agent_with_browser(
								browser_session,
								task,
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
							),
							timeout=1000,
						)

						task_result.stage_completed(Stage.RUN_AGENT)
						logger.info(f'Task {task.task_id}: Agent run completed.')
					except Exception as e:
						error = StageError(Stage.RUN_AGENT, 'exception', str(e))
						task_result.stage_failed(Stage.RUN_AGENT, error)
						logger.error(f'Task {task.task_id}: Agent run failed: {str(e) + " " + str(e.__traceback__)}')

						# Continue to server save instead of early return

				# Stage 3: Format history
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
							),
						)
						task_result.stage_completed(Stage.FORMAT_HISTORY, formatted_data)
						logger.info(f'Task {task.task_id}: Agent history formatted.')
					except Exception as e:
						error = StageError(Stage.FORMAT_HISTORY, 'exception', str(e))
						task_result.stage_failed(Stage.FORMAT_HISTORY, error)
						logger.error(f'Task {task.task_id}: History formatting failed: {str(e)}')
						# Continue to server save instead of early return

				# Stage 4: Evaluate (if we have execution data and no existing evaluation)
				if task_result.has_execution_data() and Stage.EVALUATE not in task_result.completed_stages:
					try:
						logger.info(f'Task {task.task_id}: Evaluation starting.')
						evaluation = await run_stage(
							Stage.EVALUATE, lambda: evaluate_task_result(eval_model, task_folder, use_mind2web_judge), timeout=300
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

				# Stage 5: Save to server (always attempt)
				try:
					logger.info(f'Task {task.task_id}: Saving result to server.')
					# Only save to server if URLs are provided (skip for single task mode)
					if convex_url and secret_key:
						await run_stage(
							Stage.SAVE_SERVER,
							lambda: asyncio.to_thread(
								save_result_to_server, convex_url, secret_key, task_result.server_payload if task_result else {}
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
						task.task_id, run_id, task.confirmed_task, task, max_steps_per_task, laminar_task_link
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

		logger.info(
			f'🏁 Task {task.task_id}: Completed in {total_task_time:.2f}s (semaphore held for {semaphore_hold_time:.2f}s)'
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


async def run_multiple_tasks(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	lmnr_run_id: str | None,
	laminar_eval_link: str | None,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	max_parallel_runs: int = 3,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	use_serp: bool = False,
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
	include_result: bool = False,
	highlight_elements: bool = True,
	use_mind2web_judge: bool = False,
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
					use_serp=use_serp,
					enable_memory=enable_memory,
					memory_interval=memory_interval,
					max_actions_per_step=max_actions_per_step,
					validate_output=validate_output,
					planner_llm=planner_llm,
					planner_interval=planner_interval,
					include_result=include_result,
					highlight_elements=highlight_elements,
					use_mind2web_judge=use_mind2web_judge,
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


# Helper function to fetch tasks from the server
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
		response = requests.post(endpoint_url, headers=headers, json=payload)

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


# Helper function to get git information
def get_git_info():
	"""Retrieves git branch, commit hash, commit timestamp, and repository URL using subprocess."""
	try:
		branch = subprocess.run(
			['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True, check=True
		).stdout.strip()
		commit_hash = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
		# Get commit timestamp as Unix epoch integer
		commit_timestamp_str = subprocess.run(
			['git', 'log', '-1', '--format=%ct'], capture_output=True, text=True, check=True
		).stdout.strip()
		commit_timestamp = int(commit_timestamp_str)
		# Get repository URL
		repo_url = subprocess.run(
			['git', 'config', '--get', 'remote.origin.url'], capture_output=True, text=True, check=True
		).stdout.strip()
		return {'branch': branch, 'hash': commit_hash, 'timestamp': commit_timestamp, 'repo': repo_url}
	except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
		logger.warning(f'Could not retrieve git info: {type(e).__name__}: {e}. Using defaults.')
		return {
			'branch': 'unknown',
			'hash': 'unknown',
			'timestamp': int(time.time()),  # Fallback to current time
			'repo': 'unknown',
		}


# Helper function to start a new run on the server
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
		response = requests.post(endpoint_url, headers=headers, json=payload)
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


# Helper function to save a task result to the server
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
		response = requests.post(endpoint_url, headers=headers, json=result_details)

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


async def run_evaluation_pipeline(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	test_case: str,
	user_message: str,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	max_parallel_runs: int = 3,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	use_serp: bool = False,
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
		max_parallel_runs=max_parallel_runs,
		max_steps_per_task=max_steps_per_task,
		start_index=start_index,
		end_index=end_index,
		headless=headless,
		use_vision=use_vision,
		use_serp=use_serp,
		enable_memory=enable_memory,
		memory_interval=memory_interval,
		max_actions_per_step=max_actions_per_step,
		validate_output=validate_output,
		planner_llm=planner_llm,
		planner_interval=planner_interval,
		include_result=include_result,
		highlight_elements=highlight_elements,
		use_mind2web_judge=use_mind2web_judge,
	)


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
		'--eval-model', type=str, default='gpt-4o', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for evaluation'
	)
	parser.add_argument('--no-vision', action='store_true', help='Disable vision capabilities in the agent')

	parser.add_argument('--user-message', type=str, default='', help='User message to include in the run')
	parser.add_argument('--eval-group', type=str, default='', help='Evaluation group to include in the run')
	parser.add_argument('--developer-id', type=str, default=None, help='Name of the developer starting the run')
	parser.add_argument('--use-serp', action='store_true', help='Use SERP search instead of Google search')
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
	# Run tasks and evaluate
	load_dotenv()

	# --- Load Environment Variables (Always) ---
	CONVEX_URL = os.getenv('EVALUATION_TOOL_URL') or ''
	SECRET_KEY = os.getenv('EVALUATION_TOOL_SECRET_KEY') or ''

	# --- Load Tasks (Either Single Task or from Server) ---
	tasks = []
	task_id = None  # Initialize for proper scoping

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
				f'Error creating Task objects from fetched data. Ensure the data structure includes required fields (task_id, confirmed_task). Known optional fields: website, reference_length, level, cluster_id, login_cookie, login_type, category. Any additional fields will be accepted dynamically. Error: {type(e).__name__}: {e}'
			)
			logger.error(f'First item in fetched data: {fetched_task_data[0] if fetched_task_data else "None"}')
			exit(1)
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
				max_parallel_runs=parallel_runs,
				max_steps_per_task=args.max_steps,
				start_index=start_index,
				end_index=end_index,
				headless=args.headless,
				use_vision=not args.no_vision,
				use_serp=args.use_serp,
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
