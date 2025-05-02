# ==============================================================================================================
# Documentation for this evaluation file.
# The import


# Here is the command to run the evaluation:
# python eval/service.py --parallel_runs 5 --parallel_evaluations 5 --max-steps 25 --start 0 --end 100 --model gpt-4o
# options:
# --parallel_runs: Number of parallel tasks to run
# --max-steps: Maximum steps per task
# --start: Start index
# --end: End index (exclusive)
# --headless: Run in headless mode

# Here is the command to run the evaluation only:
# python eval/service.py --evaluate-only
# options:
# --parallel_evaluations: Number of parallel evaluations to run

# ==============================================================================================================


# ==============================================================================================================
# This is the LLM as a judge evaluation system from the OSU-NLP Group paper
# Any adaptiations made should be explicitly stated here:
# Adaptations:
# We are using our langchain wrapper for the OpenAI API
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
import io
import logging
import re
import shutil

import anyio
from PIL import Image

MAX_IMAGE = 5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
	response = await asyncio.to_thread(model.invoke, messages)
	return response.content


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
	response = await asyncio.to_thread(model.invoke, messages)
	return response.content


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
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic.types import SecretStr

from browser_use import Agent, Browser, BrowserConfig

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
	'gemini-2.0-flash-exp': {'provider': 'google', 'model_name': 'gemini-2.0-flash-exp', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.5-pro': {'provider': 'google', 'model_name': 'gemini-2.5-pro-preview-03-25', 'api_key_env': 'GEMINI_API_KEY'},
	# OpenAI
	'gpt-4.1': {'provider': 'openai', 'model_name': 'gpt-4.1-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o': {'provider': 'openai', 'model_name': 'gpt-4o', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o-mini': {'provider': 'openai', 'model_name': 'gpt-4o-mini', 'api_key_env': 'OPENAI_API_KEY'},
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
}


def get_llm(model_name: str):
	"""Instantiates the correct LangChain ChatModel based on the model name."""
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

	api_key_secret = SecretStr(api_key) if api_key else None

	if provider == 'openai':
		kwargs = {
			'model': config['model_name'],
			'temperature': 0.0,
		}
		if api_key_secret:
			kwargs['api_key'] = api_key_secret
		return ChatOpenAI(**kwargs)
	elif provider == 'anthropic':
		# Note: Anthropic client often uses env var ANTHROPIC_API_KEY directly if api_key=None
		kwargs = {
			'model_name': config['model_name'],
			'temperature': 0.0,
			'timeout': 100,
			'stop': None,
		}
		if api_key_secret:
			kwargs['api_key'] = api_key_secret
		return ChatAnthropic(**kwargs)
	elif provider == 'google':
		# Note: Google client often uses env var GOOGLE_API_KEY directly if api_key=None
		kwargs = {
			'model': config['model_name'],
			'temperature': 0.0,
		}
		if api_key_secret:
			kwargs['api_key'] = api_key_secret
		return ChatGoogleGenerativeAI(**kwargs)
	elif provider == 'openai_compatible':
		# Note: OpenAI client often uses env var OPENAI_API_KEY directly if api_key=None and no base_url specified
		# Providing base_url requires explicitly passing the key for that endpoint.
		kwargs = {
			'model': config['model_name'],
			'base_url': config['base_url'],
			'temperature': 0.0,
		}
		if api_key_secret:
			kwargs['api_key'] = api_key_secret
		# Ensure api_key is provided if base_url is set and key exists
		elif config.get('base_url'):
			# If base_url is present but key is missing, we might still error depending on the endpoint's auth requirements.
			# Log a warning here, the constructor will likely raise an error if the key is truly required.
			logger.warning(
				f'API key for {model_name} at {config["base_url"]} is missing, but base_url is specified. Authentication may fail.'
			)
		return ChatOpenAI(**kwargs)
	else:
		raise ValueError(f'Unknown provider: {provider}')


class Task:
	def __init__(self, task_id, confirmed_task, website, reference_length, level):
		self.task_id = task_id
		self.confirmed_task = confirmed_task
		self.website = website
		self.reference_length = reference_length
		self.level = level

	def __str__(self):
		return f'Task(task_id={self.task_id}, confirmed_task={self.confirmed_task}, website={self.website}, reference_length={self.reference_length}, level={self.level})'

	def __repr__(self):
		return self.__str__()


class TaskTracker:
	def __init__(self, task_id: str, task_text: str, run_id: str):
		self.task_id = task_id
		self.task_text = task_text
		self.run_id = run_id
		self.result_folder = Path(f'saved_trajectories/{task_id}')
		self.trajectory_folder = self.result_folder / 'trajectory'
		self.step_results = []
		self.step_counter = 0
		self.screenshots = []
		self.setup_folders()

	def setup_folders(self):
		"""Create the necessary folder structure"""
		self.result_folder.mkdir(parents=True, exist_ok=True)
		self.trajectory_folder.mkdir(parents=True, exist_ok=True)

	async def on_step_start(self, agent):
		"""Record information at the start of a step"""
		self.current_step = {'step_number': self.step_counter, 'start_time': datetime.now().isoformat(), 'actions': []}

	async def on_step_end(self, agent):
		"""Record information at the end of a step"""
		# Take screenshot
		browser_context = agent.browser_context
		screenshot_b64 = await browser_context.take_screenshot()
		screenshot_path = self.trajectory_folder / f'step_{self.step_counter}.png'

		# Save screenshot to file
		async with await anyio.open_file(screenshot_path, 'wb') as f:
			await f.write(base64.b64decode(screenshot_b64))

		# Save screenshot path
		self.screenshots.append(str(screenshot_path))

		# Record action and result
		if agent.state.last_result:
			for result in agent.state.last_result:
				self.current_step['actions'].append(
					{
						'content': result.extracted_content,
						'error': result.error,
						'is_done': result.is_done,
						'success': result.success,
					}
				)

		# Record end time
		self.current_step['end_time'] = datetime.now().isoformat()
		self.current_step['screenshot_path'] = str(screenshot_path)

		# Add to step results
		self.step_results.append(self.current_step)
		self.step_counter += 1

		# Save intermediate results
		self.save_results()  # Save progress after each step

	def save_results(self):
		"""Save the consolidated results"""
		# Create the final result object

		# Ensure action history contains only strings, replacing None with "None"
		action_history = []
		for step in self.step_results:
			if step['actions']:
				content = step['actions'][-1]['content']
				action_history.append(content if content is not None else 'None')
			else:
				action_history.append('None')  # Handle steps with no actions

		formatted_result = {
			'task_id': self.task_id,
			'run_id': self.run_id,
			'task': self.task_text,
			'steps': self.step_results,
			'action_history': action_history,  # Use the cleaned list
			'screenshot_paths': self.screenshots,
			'final_result_response': (
				last_action['content'] if (last_action := self.step_results[-1]['actions'][-1])['is_done'] else None
			),
			'self_report_completed': self.step_results[-1]['actions'][-1]['is_done']
			if self.step_results and self.step_results[-1]['actions']
			else False,
			'self_report_success': self.step_results[-1]['actions'][-1]['success']
			if self.step_results and self.step_results[-1]['actions']
			else None,
		}

		# Save to file
		with open(self.result_folder / 'result.json', 'w') as f:
			json.dump(formatted_result, f, indent=2)

		return formatted_result


async def run_agent_with_tracing(
	task: Task, llm: BaseChatModel, run_id: str, browser: Browser | None = None, max_steps: int = 25, use_vision: bool = True
):
	try:
		# Create task tracker
		tracker = TaskTracker(task.task_id, task.confirmed_task, run_id)

		browser = browser or Browser()

		agent = Agent(
			task=task.confirmed_task,
			llm=llm,
			browser=browser,
			use_vision=use_vision,
			source='eval_platform',  # Override source detection
		)

		# Pass our hook functions
		result = await agent.run(max_steps=max_steps, on_step_start=tracker.on_step_start, on_step_end=tracker.on_step_end)

		# Save final results
		final_results = tracker.save_results()

		return result
	finally:
		# Ensure proper cleanup
		await asyncio.sleep(0.1)  # Give a moment for any pending tasks to complete
		if not browser:
			await agent.close()  # This will close the browser if we created it


async def judge_task_result(model, task_folder: Path, score_threshold: float = 3) -> dict:
	"""
	Judge a single task result based on the success value of the final action.

	Args:
	    task_folder: Path to the task result folder

	Returns:
	    Dictionary containing judgment results
	"""
	result_file = task_folder / 'result.json'
	if not result_file.exists():
		return {'task_id': task_folder.name, 'judgement': None, 'success': False, 'error': 'No result.json found', 'score': 0.0}

	try:
		async with await anyio.open_file(result_file) as f:
			result = json.loads(await f.read())

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

			# Final steps to get judgement - run invoke in a thread
			judgement_msg = await asyncio.to_thread(model.invoke, messages)
			judgement = judgement_msg.content

			if 'success' in judgement.lower().split('status:')[1]:  # This is the official criteria for success
				evaluation = {'task_id': task_folder.name, 'judgement': judgement, 'success': True, 'error': None, 'score': 1.0}
			else:  # This is the official criteria for failure
				evaluation = {'task_id': task_folder.name, 'judgement': judgement, 'success': False, 'error': None, 'score': 0.0}

			# Save the Online_Mind2Web_evaluation into the result.json file
			result['Online_Mind2Web_evaluation'] = evaluation
			with anyio.open_file(result_file, 'w') as f:
				await f.write(json.dumps(result, indent=2))

			return evaluation

		except Exception as err:
			return {
				'task_id': task_folder.name,
				'judgement': None,
				'success': False,
				'error': f'{type(err).__name__}: {err}',
				'score': 0.0,
			}

	except Exception as err:
		return {
			'task_id': task_folder.name,
			'judgement': None,
			'success': False,
			'error': f'{type(err).__name__}: {err}',
			'score': 0.0,
		}


def calculate_local_summary(results_dir: str | None = None) -> dict:
	"""
	Calculates a summary of task results by reading the saved result.json files.
	Does not make any network requests.

	Args:
		results_dir: Directory where task results are stored (default: 'saved_trajectories')

	Returns:
		Dictionary containing total_tasks, successful_tasks, success_rate, and average_score
	"""
	if results_dir is None:
		results_dir = 'saved_trajectories'

	path = Path(results_dir)
	if not path.is_dir():
		logger.warning(f'Results directory {results_dir} does not exist')
		return {
			'timestamp': datetime.now().isoformat(),
			'total_tasks': 0,
			'successful_tasks': 0,
			'failed_tasks': 0,
			'success_rate': 0,
			'average_score': 0,
		}

	# Collect all task folders
	task_folders = [f for f in path.iterdir() if f.is_dir()]
	total_tasks = len(task_folders)
	successful_tasks = 0
	total_score = 0.0
	results_with_score = 0

	for folder in task_folders:
		result_file = folder / 'result.json'
		if result_file.exists():
			try:
				with open(result_file) as f:
					result_data = json.load(f)

				# Look for evaluation data
				evaluation = result_data.get('Online_Mind2Web_evaluation', {})
				if evaluation:
					if evaluation.get('success', False):
						successful_tasks += 1

					score = evaluation.get('score', 0.0)
					if score > 0:
						total_score += score
						results_with_score += 1
			except Exception as e:
				logger.error(f'Error reading result file {result_file}: {type(e).__name__}: {e}')

	# Calculate statistics
	failed_tasks = total_tasks - successful_tasks
	success_rate = successful_tasks / total_tasks if total_tasks > 0 else 0
	average_score = total_score / results_with_score if results_with_score > 0 else 0

	return {
		'timestamp': datetime.now().isoformat(),
		'total_tasks': total_tasks,
		'successful_tasks': successful_tasks,
		'failed_tasks': failed_tasks,
		'success_rate': success_rate,
		'average_score': average_score,
	}


async def run_task_with_semaphore(
	task: Task,
	run_id: str,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	llm: BaseChatModel,
	max_steps_per_task: int,
	headless: bool,
	use_vision: bool,
	semaphore_runs: asyncio.Semaphore,  # Pass semaphore as argument
) -> dict:
	"""Run a single task with semaphore, sequential execution, and robust error handling"""
	# Acquire semaphore before starting any task-specific logic
	async with semaphore_runs:
		# --- Initialize State & Payload ---
		task_folder = Path(f'saved_trajectories/{task.task_id}')
		result_file = task_folder / 'result.json'

		# Flags to track progress and errors
		execution_needed = True
		execution_succeeded = False
		evaluation_needed = True
		evaluation_succeeded = True  # Default to True, set to False if eval is needed but fails
		local_processing_error = None

		# Initialize the payload with basic info and default failure/unevaluated states
		server_payload = {
			'runId': run_id,
			'taskId': task.task_id,
			'task': task.confirmed_task,
			'actionHistory': [],
			'finalResultResponse': 'None',  # Default if execution doesn't happen or fails early
			'selfReportCompleted': False,
			'selfReportSuccess': None,
			'onlineMind2WebEvaluationJudgement': 'Not Attempted',
			'onlineMind2WebEvaluationError': None,
			'onlineMind2WebEvaluationSuccess': False,
			'onlineMind2WebEvaluationScore': 0.0,
		}

		# Initialize the return value for local processing status
		local_task_status = {'task_id': task.task_id, 'success': False, 'error': None}

		# --- Main Sequential Logic with Error Handling ---
		try:
			# 1. Check for Existing Result
			if result_file.exists():
				logger.info(f'Task {task.task_id}: Found existing result file.')
				try:
					with anyio.open_file(result_file) as f:
						existing_result = json.loads(await f.read())

					# Populate payload from existing file
					server_payload['actionHistory'] = existing_result.get('action_history', [])
					server_payload['finalResultResponse'] = existing_result.get('final_result_response', 'None')
					server_payload['selfReportCompleted'] = existing_result.get('self_report_completed', False)
					server_payload['selfReportSuccess'] = existing_result.get('self_report_success', None)

					# Check if evaluation data is also present
					if existing_eval := existing_result.get('Online_Mind2Web_evaluation'):
						logger.info(f'Task {task.task_id}: Found existing evaluation data.')
						# Ensure judgement is stored as string "None" if it was null/None in cache
						cached_judgement = existing_eval.get('judgement')
						server_payload['onlineMind2WebEvaluationJudgement'] = (
							cached_judgement if cached_judgement is not None else 'None'
						)
						server_payload['onlineMind2WebEvaluationError'] = existing_eval.get('error')
						server_payload['onlineMind2WebEvaluationSuccess'] = existing_eval.get('success', False)
						server_payload['onlineMind2WebEvaluationScore'] = existing_eval.get('score', 0.0)
						evaluation_needed = False  # Don't re-evaluate if already present
						evaluation_succeeded = True  # Assume cached evaluation was successful
					else:
						# Evaluation not found, needs to run
						evaluation_needed = True
						evaluation_succeeded = False  # Mark as needing evaluation initially

					execution_needed = False  # Don't execute if result exists
					execution_succeeded = True  # Mark as "success" in terms of having data
					logger.info(f'Task {task.task_id}: Successfully loaded existing result. Skipping execution.')

				except Exception as e:
					logger.warning(
						f'Task {task.task_id}: Error reading existing result file {result_file}: {type(e).__name__}: {str(e)}. Proceeding with execution.'
					)
					# Keep execution_needed = True, payload defaults remain
					execution_needed = True
					execution_succeeded = False
					evaluation_needed = True  # Might need eval after execution
					evaluation_succeeded = False  # Reset eval status

			# 2. Execute Task (if needed)
			if execution_needed:
				logger.info(f'Task {task.task_id}: Starting execution.')
				browser = None  # Ensure browser is defined for finally block
				try:
					browserConfig = BrowserConfig(headless=headless)
					browser = Browser(config=browserConfig)
					# Pass the llm to run_agent_with_tracing
					result = await run_agent_with_tracing(
						task=task,
						llm=llm,
						browser=browser,
						max_steps=max_steps_per_task,
						use_vision=use_vision,
						run_id=run_id,  # run_agent_with_tracing handles saving result.json
					)
					logger.info(f'Task {task.task_id}: Execution completed.')
					execution_succeeded = True
					evaluation_needed = True  # Need to evaluate the new result
					evaluation_succeeded = False  # Reset eval status

					# Load the result file that should have just been created
					if result_file.exists():
						async with await anyio.open_file(result_file) as f:
							run_result_data = json.loads(await f.read())
						server_payload['actionHistory'] = run_result_data.get('action_history', [])
						server_payload['finalResultResponse'] = run_result_data.get('final_result_response', 'None')
						server_payload['selfReportCompleted'] = run_result_data.get('self_report_completed', False)
						server_payload['selfReportSuccess'] = run_result_data.get('self_report_success', None)
					else:
						# This is unexpected if run_agent_with_tracing succeeded
						logger.error(
							f'Task {task.task_id}: Result file {result_file} missing after presumed successful execution.'
						)
						raise FileNotFoundError(f'Result file not found after execution for task {task.task_id}')

				except Exception as e:
					logger.error(
						f'Task {task.task_id}: Error during execution with Type: {type(e).__name__} and Message: {str(e)}',
						exc_info=True,
					)  # Add stack trace
					execution_succeeded = False
					evaluation_needed = False  # Cannot evaluate if execution failed
					evaluation_succeeded = False  # Evaluation definitely didn't succeed
					# Update payload to reflect execution failure
					server_payload['finalResultResponse'] = f'Execution Error: {type(e).__name__}: {str(e)}'
					server_payload['onlineMind2WebEvaluationJudgement'] = 'Execution Failed'
					server_payload['onlineMind2WebEvaluationError'] = f'Execution Error: {type(e).__name__}'
				finally:
					if browser:
						try:
							await browser.close()
						except Exception as browser_close_e:
							logger.warning(
								f'Task {task.task_id}: Error closing browser: {type(browser_close_e).__name__}: {browser_close_e}'
							)

			# 3. Evaluate Task (if needed and possible)
			if evaluation_needed and execution_succeeded:
				logger.info(f'Task {task.task_id}: Starting evaluation.')
				try:
					# judge_task_result will attempt evaluation and save it back into result.json if successful
					evaluation = await judge_task_result(eval_model, task_folder, score_threshold=3)

					# Update payload directly from the evaluation function's return value
					if evaluation:
						# Ensure judgement is stored as string "None" if the evaluation returned None
						judgement_value = evaluation.get('judgement')
						server_payload['onlineMind2WebEvaluationJudgement'] = (
							judgement_value if judgement_value is not None else 'None'
						)
						server_payload['onlineMind2WebEvaluationError'] = evaluation.get('error')
						server_payload['onlineMind2WebEvaluationSuccess'] = evaluation.get('success', False)
						server_payload['onlineMind2WebEvaluationScore'] = evaluation.get('score', 0.0)
						# Mark evaluation as succeeded only if the evaluation itself didn't report an error
						if evaluation.get('error'):
							logger.warning(
								f'Task {task.task_id}: Evaluation completed but reported an error: {evaluation.get("error")}'
							)
							evaluation_succeeded = False
						else:
							evaluation_succeeded = True  # Mark evaluation as successfully completed
							logger.info(f'Task {task.task_id}: Evaluation successfully completed.')

					else:
						# Should not happen based on judge_task_result structure, but handle defensively
						logger.error(f'Task {task.task_id}: Evaluation function returned None.')
						evaluation_succeeded = False  # Mark as failed if None returned
						server_payload['onlineMind2WebEvaluationJudgement'] = 'Evaluation Returned None'
						server_payload['onlineMind2WebEvaluationError'] = 'Evaluation function returned None'

				except Exception as e:
					logger.error(
						f'Task {task.task_id}: Error during evaluation process: {type(e).__name__}: {str(e)}', exc_info=True
					)  # Add stack trace
					evaluation_succeeded = False
					# Update payload to reflect evaluation failure
					server_payload['onlineMind2WebEvaluationJudgement'] = 'Evaluation Process Error'
					server_payload['onlineMind2WebEvaluationError'] = f'Evaluation Error: {type(e).__name__}: {str(e)}'
					# Keep Success/Score as False/0.0 from defaults

		except Exception as outer_e:
			# Catch any unexpected errors in the flow above (e.g., reading existing file, setup issues)
			logger.critical(f'Task {task.task_id}: CRITICAL UNHANDLED ERROR during processing: {str(outer_e)}', exc_info=True)
			local_processing_error = f'Critical flow error: {str(outer_e)}'
			# Ensure payload reflects a critical failure state
			server_payload['finalResultResponse'] = f'Critical Error: {str(outer_e)}'
			server_payload['onlineMind2WebEvaluationJudgement'] = 'Critical System Error'
			server_payload['onlineMind2WebEvaluationError'] = local_processing_error
			server_payload['onlineMind2WebEvaluationSuccess'] = False
			server_payload['onlineMind2WebEvaluationScore'] = 0.0
			execution_succeeded = False  # Mark stages as failed due to outer error
			evaluation_succeeded = False

		# --- Final Step: Save to Server (Always Attempt) ---
		logger.info(f'Task {task.task_id}: Attempting to save final result to server...')
		try:
			save_success = save_task_result_to_server(convex_url, secret_key, server_payload)
			if save_success:
				logger.info(f'Task {task.task_id}: Successfully saved result to server.')
			else:
				logger.warning(f'Task {task.task_id}: Failed to save result to server (API issue or invalid payload).')
				# Optionally accumulate this failure into local_processing_error
				if local_processing_error:
					local_processing_error += '; Server save failed'
				else:
					local_processing_error = 'Server save failed'

		except Exception as e:
			logger.error(f'Task {task.task_id}: Exception during attempt to save result to server: {type(e).__name__}: {str(e)}')
			# Optionally accumulate this failure
			if local_processing_error:
				local_processing_error += f'; Server save exception: {str(e)}'
			else:
				local_processing_error = f'Server save exception: {str(e)}'

		# --- Return Local Processing Status ---
		# Overall success requires successful execution (or loading existing) AND successful evaluation (if needed).
		local_task_status['success'] = execution_succeeded and evaluation_succeeded
		local_task_status['error'] = local_processing_error  # Report any accumulated local errors

		return local_task_status


async def run_multiple_tasks(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	max_parallel_runs: int = 3,
	max_parallel_evaluations: int = 5,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	fresh_start: bool = True,
) -> dict:
	"""
	Run multiple tasks in parallel and evaluate results.
	"""
	semaphore_runs = asyncio.Semaphore(max_parallel_runs)
	tasks_to_run = tasks[start_index:end_index] if end_index else tasks[start_index:]

	# Run all tasks in parallel with additional parameters
	task_results = await asyncio.gather(
		*(
			run_task_with_semaphore(
				task=task,
				run_id=run_id,
				convex_url=convex_url,
				secret_key=secret_key,
				eval_model=eval_model,
				llm=llm,  # Pass the agent LLM
				max_steps_per_task=max_steps_per_task,
				headless=headless,
				use_vision=use_vision,
				semaphore_runs=semaphore_runs,  # Pass the semaphore
			)
			for task in tasks_to_run
		)
	)

	# After all tasks are complete, calculate a local summary
	logger.info('All tasks completed. Calculating result summary...')
	summary = calculate_local_summary()

	# Log the summary statistics
	logger.info(f'Completed {summary["total_tasks"]} tasks')
	logger.info(f'Success rate: {summary["success_rate"]:.2%}')
	logger.info(f'Average score: {summary["average_score"]:.2f}')

	return {'task_results': task_results, 'summary': summary}


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
	"""Retrieves git branch, commit hash, and commit timestamp using subprocess."""
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
		return {'branch': branch, 'hash': commit_hash, 'timestamp': commit_timestamp}
	except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
		logger.warning(f'Could not retrieve git info: {type(e).__name__}: {e}. Using defaults.')
		return {
			'branch': 'unknown',
			'hash': 'unknown',
			'timestamp': int(time.time()),  # Fallback to current time
		}


# Helper function to start a new run on the server
def start_new_run(convex_url: str, secret_key: str, run_details: dict):
	"""Sends a request to start a new evaluation run and returns the run ID."""
	if not convex_url or not secret_key:
		logger.error('Error: Convex URL or Secret Key not provided for starting run.')
		return None

	endpoint_url = f'{convex_url}/api/startRun'
	headers = {
		'Authorization': f'Bearer {secret_key}',
		'Content-Type': 'application/json',
	}

	logger.info(f'Sending request to start run at {endpoint_url}...')
	# Avoid logging secret key in run_details if it were ever passed
	loggable_details = {k: v for k, v in run_details.items() if k != 'secret_key'}
	logger.info(f'Run details: {json.dumps(loggable_details, indent=2)}')

	try:
		response = requests.post(endpoint_url, headers=headers, json=run_details)
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


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Run and evaluate browser automation tasks')
	parser.add_argument('--parallel_runs', type=int, default=3, help='Number of parallel tasks to run')
	parser.add_argument('--parallel_evaluations', type=int, default=5, help='Number of parallel evaluations to run')
	parser.add_argument('--max-steps', type=int, default=25, help='Maximum steps per task')
	parser.add_argument('--start', type=int, default=0, help='Start index')
	parser.add_argument('--end', type=int, default=None, help='End index (exclusive)')
	parser.add_argument('--headless', action='store_true', help='Run in headless mode')
	parser.add_argument('--evaluate-only', action='store_true', help='Only evaluate existing results without running new tasks')
	parser.add_argument(
		'--model', type=str, default='gpt-4o', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for the agent'
	)
	parser.add_argument('--no-vision', action='store_true', help='Disable vision capabilities in the agent')
	parser.add_argument(
		'--fresh-start',
		type=lambda x: (str(x).lower() == 'true'),
		default=True,
		help='Clear saved_trajectories before starting. Set to False to keep existing trajectories (default: True)',
	)
	parser.add_argument('--user-message', type=str, default='', help='User message to include in the run')
	args = parser.parse_args()

	# Set up logging - Make sure logger is configured before use in fetch function
	logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
	logger = logging.getLogger(__name__)  # Define logger for the module

	if args.evaluate_only:
		# Just evaluate existing results
		logger.info('Evaluating existing results...')
		summary = calculate_local_summary()

		# Save evaluation results
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		eval_file = f'saved_trajectories/evaluation_summary_{timestamp}.json'
		with open(eval_file, 'w') as f:
			json.dump(summary, f, indent=2)

		logger.info(f'Evaluation complete. Success rate: {summary["success_rate"]:.2%}')
		logger.info(f'Average score: {summary["average_score"]:.2f}')
		logger.info(f'Full results saved to {eval_file}')

	else:
		logger.info('Running tasks...')
		# Run tasks and evaluate
		load_dotenv()

		# --- Clear trajectories if fresh_start is True ---
		results_dir_path = Path('saved_trajectories')
		if args.fresh_start:
			logger.info(f'--fresh-start is True. Clearing {results_dir_path}...')
			if results_dir_path.exists():
				try:
					shutil.rmtree(results_dir_path)
					logger.info(f'Successfully removed {results_dir_path}.')
				except OSError as e:
					logger.error(f'Error removing directory {results_dir_path}: {type(e).__name__}: {e}')
					# Decide if you want to exit or continue
					# exit(1) # Uncomment to exit on error
			else:
				logger.info(f'{results_dir_path} does not exist, no need to clear.')

			# Recreate the directory
			try:
				results_dir_path.mkdir(parents=True, exist_ok=True)
				logger.info(f'Recreated directory {results_dir_path}.')
			except OSError as e:
				logger.error(f'Error creating directory {results_dir_path}: {type(e).__name__}: {e}')
				# exit(1) # Uncomment to exit on error
		else:
			logger.info('--fresh-start is False. Existing trajectories in saved_trajectories will be kept.')
		# -------------------------------------------------

		# --- Fetch Tasks from Server ---
		CONVEX_URL = os.getenv('EVALUATION_TOOL_URL')
		SECRET_KEY = os.getenv('EVALUATION_TOOL_SECRET_KEY')
		TEST_CASE_NAME = 'OnlineMind2Web'  # Name of the test case to fetch

		if not CONVEX_URL or not SECRET_KEY:
			logger.error('Error: EVALUATION_TOOL_URL or EVALUATION_TOOL_SECRET_KEY environment variables not set.')
			exit(1)  # Exit if config is missing

		logger.info(f"Attempting to fetch task list '{TEST_CASE_NAME}' from server...")
		fetched_task_data = fetch_tasks_from_server(CONVEX_URL, SECRET_KEY, TEST_CASE_NAME)

		if fetched_task_data is None:
			logger.error('Failed to fetch tasks from the server. Exiting.')
			exit(1)  # Exit if fetch fails

		try:
			tasks = [Task(**task_data) for task_data in fetched_task_data]
			logger.info(f'Successfully loaded {len(tasks)} tasks from the server.')
		except TypeError as e:
			logger.error(
				f'Error creating Task objects from fetched data. Ensure the data structure matches Task requirements (task_id, confirmed_task, etc.). Error: {type(e).__name__}: {e}'
			)
			logger.error(f'First item in fetched data: {fetched_task_data[0] if fetched_task_data else "None"}')
			exit(1)
		# -----------------------------

		# --- Start Run on Server ---
		logger.info('Attempting to start a new run on the server...')
		git_info = get_git_info()

		# Collect additional data from args to store with the run
		additional_run_data = {
			'max_steps': args.max_steps,
			'parallel_runs': args.parallel_runs,
			'parallel_evaluations': args.parallel_evaluations,
			'start_index': args.start,
			'end_index': args.end,
			'headless': args.headless,
			'use_vision': not args.no_vision,
			'task_source': TEST_CASE_NAME,
		}

		run_data = {
			'model': args.model,
			'gitBranch': git_info['branch'],
			'gitCommitHash': git_info['hash'],
			'gitCommitTimestamp': git_info['timestamp'],
			'userMessage': args.user_message,
			'totalTasks': args.end - args.start,
			'additionalData': additional_run_data,
		}

		run_id = start_new_run(CONVEX_URL, SECRET_KEY, run_data)

		if not run_id:
			logger.error('Failed to start a new run on the server. Exiting.')
			exit(1)

		logger.info(f'Successfully obtained run ID: {run_id}. Proceeding with tasks...')
		# -------------------------

		# Get the selected LLM
		llm = get_llm(args.model)

		results = asyncio.run(
			run_multiple_tasks(
				tasks=tasks,
				llm=llm,  # Pass the instantiated llm
				run_id=run_id,
				convex_url=CONVEX_URL,
				secret_key=SECRET_KEY,
				eval_model=llm,
				max_parallel_runs=args.parallel_runs,
				max_parallel_evaluations=args.parallel_evaluations,
				max_steps_per_task=args.max_steps,
				start_index=args.start,
				end_index=args.end,
				headless=args.headless,
				use_vision=not args.no_vision,
				fresh_start=args.fresh_start,
			)
		)

		logger.info('Task completed. Saving results...')
		# Save results
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		results_file = f'saved_trajectories/eval_results_{timestamp}.json'

		# Convert results to JSON-serializable format
		serializable_results = {'summary': results['summary']}

		with open(results_file, 'w') as f:
			json.dump(serializable_results, f, indent=2)

		# Print summary
		summary = results['summary']
		logger.info(f'Completed {summary["total_tasks"]} tasks.')
		logger.info(f'Success rate: {summary["success_rate"]:.2%}')
		logger.info(f'Average score: {summary["average_score"]:.2f}')
		logger.info(f'Results saved to {results_file}')
