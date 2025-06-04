# ==============================================================================================================
# Documentation for this evaluation file.

# Here is the command to run the evaluation:
# python eval/service.py --parallel-runs 2 --max-steps 25 --start 0 --end 100 --model llama-4-maverick --eval-model gpt-4.1 --no-vision --eval-group "PRTests" --user-message "message here"

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
import http.client
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

from browser_use import ActionResult, Agent, BrowserProfile, BrowserSession, Controller
from browser_use.agent.memory import MemoryConfig
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
}

# Check for SERPER API key
SERPER_API_KEY = os.getenv('SERPER_API_KEY')
if not SERPER_API_KEY:
	logger.warning('SERPER_API_KEY is not set. Search functionality will not be available.')


def create_controller_with_serp_search():
	"""Create a controller with SERP search instead of Google search"""
	controller = Controller(exclude_actions=['search_google'])

	@controller.registry.action('Search the web for a specific query')
	async def search_web(query: str):
		"""Search the web using Serper API"""
		if not SERPER_API_KEY:
			return ActionResult(extracted_content='Search unavailable: SERPER_API_KEY not configured', include_in_memory=False)

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

			return ActionResult(extracted_content=serp_data_str, include_in_memory=False)

		except Exception as e:
			logger.error(f'Error in SERP search: {type(e).__name__}: {e}')
			return ActionResult(extracted_content=f'Search error: {str(e)}', include_in_memory=False)

	return controller


def create_controller(use_serp: bool = False):
	"""Create a controller, optionally with SERP search"""
	if use_serp:
		return create_controller_with_serp_search()
	else:
		return Controller()


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
	match provider:
		case 'openai':
			kwargs = {'model': config['model_name'], 'temperature': 0.0}
			# Must set temperatue=1 if model is gpt-o4-mini
			if model_name == 'gpt-o4-mini':
				kwargs['temperature'] = 1
			if api_key_secret:
				kwargs['api_key'] = api_key_secret
			return ChatOpenAI(**kwargs)
		case 'anthropic':
			kwargs = {'model_name': config['model_name'], 'temperature': 0.0, 'timeout': 100, 'stop': None}
			if api_key_secret:
				kwargs['api_key'] = api_key_secret
			return ChatAnthropic(**kwargs)
		case 'google':
			kwargs = {'model': config['model_name'], 'temperature': 0.0}
			if api_key_secret:
				kwargs['api_key'] = api_key_secret
			return ChatGoogleGenerativeAI(**kwargs)
		case 'openai_compatible':
			kwargs = {'model': config['model_name'], 'base_url': config['base_url'], 'temperature': 0.0}
			if api_key_secret:
				kwargs['api_key'] = api_key_secret
			elif config.get('base_url'):
				logger.warning(
					f'API key for {model_name} at {config["base_url"]} is missing, but base_url is specified. Authentication may fail.'
				)
			return ChatOpenAI(**kwargs)
		case _:
			raise ValueError(f'Unknown provider: {provider}')


def clean_action_dict(action_dict: dict) -> dict:
	return {k: clean_action_dict(v) if isinstance(v, dict) else v for k, v in action_dict.items() if v is not None}


async def reformat_agent_history(
	agent_history: AgentHistoryList, task_id: str, run_id: str, task: str, base_path: str = 'saved_trajectories'
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

	# Create results structure with new fields
	results = {
		'task_id': task_id,
		'run_id': run_id,
		'task': task,
		'action_history': action_history,
		'screenshot_paths': screenshot_paths,
		'final_result_response': final_result,
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


class Task:
	def __init__(self, task_id, confirmed_task, website=None, reference_length=None, level=None, cluster_id=None):
		self.task_id = task_id
		self.confirmed_task = confirmed_task
		self.website = website
		self.reference_length = reference_length
		self.level = level
		self.cluster_id = cluster_id

	def __str__(self):
		return f'Task(task_id={self.task_id}, confirmed_task={self.confirmed_task}, website={self.website}, reference_length={self.reference_length}, level={self.level}, cluster_id={self.cluster_id})'

	def __repr__(self):
		return self.__str__()


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
			async with await anyio.open_file(result_file, 'w') as f:
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


from dataclasses import dataclass
from enum import Enum
from typing import Any


class Stage(Enum):
	LOAD_EXISTING = 'load_existing'
	SETUP_BROWSER = 'setup_browser'
	RUN_AGENT = 'run_agent'
	FORMAT_HISTORY = 'format_history'
	EVALUATE = 'evaluate'
	SAVE_SERVER = 'save_server'


@dataclass
class StageError(Exception):
	stage: Stage
	error_type: str  # "timeout", "cancelled", "exception"
	message: str


class TaskResult:
	"""Simplified task state tracker with auto-updating server payload"""

	def __init__(self, task_id: str, run_id: str, task_description: str, task: Task, max_steps: int):
		self.task_id = task_id
		self.completed_stages = set()
		self.stage_data = {}  # Store actual results from each stage
		self.failed_stages = {}  # Store errors from failed stages
		self.local_error = None

		# Initialize server payload with defaults
		self.server_payload = {
			'runId': run_id,
			'taskId': task_id,
			'task': task_description,
			'taskWebsite': task.website,
			'taskReferenceLength': task.reference_length,
			'taskLevel': task.level,
			'taskClusterId': task.cluster_id,
			'actionHistory': [],
			'finalResultResponse': 'None',
			'selfReportCompleted': False,
			'selfReportSuccess': None,
			'browserCrash': False,
			'browserCrashReason': None,
			'onlineMind2WebEvaluationJudgement': 'Not Attempted',
			'onlineMind2WebEvaluationError': None,
			'onlineMind2WebEvaluationSuccess': False,
			'onlineMind2WebEvaluationScore': 0.0,
			'completeHistory': [],
			'maxSteps': max_steps,
			'tokensUsed': 0,
			'taskDuration': None,
			'steps': 0,
		}

	def stage_completed(self, stage: Stage, data: Any = None):
		"""Mark stage as completed and update server payload"""
		self.completed_stages.add(stage)
		if data is not None:
			self.stage_data[stage] = data
		self._auto_update_payload()

	def stage_failed(self, stage: Stage, error: StageError):
		"""Mark stage as failed and update server payload"""
		self.failed_stages[stage] = error
		self._auto_update_payload()

	def has_execution_data(self) -> bool:
		"""Check if we have execution data from either loading existing or completing execution"""
		return Stage.LOAD_EXISTING in self.completed_stages or Stage.FORMAT_HISTORY in self.completed_stages

	def execution_succeeded(self) -> bool:
		"""Check if execution pipeline succeeded"""
		return (
			Stage.LOAD_EXISTING in self.completed_stages or Stage.FORMAT_HISTORY in self.completed_stages
		) and not self._has_execution_failures()

	def _has_execution_failures(self) -> bool:
		"""Check if any execution-related stages failed"""
		execution_stages = {Stage.SETUP_BROWSER, Stage.RUN_AGENT, Stage.FORMAT_HISTORY}
		return any(stage in self.failed_stages for stage in execution_stages)

	def _auto_update_payload(self):
		"""Automatically update server_payload based on current state"""
		# Update execution data if available
		if Stage.LOAD_EXISTING in self.completed_stages:
			existing_data = self.stage_data[Stage.LOAD_EXISTING]
			self.server_payload.update(
				{
					'actionHistory': existing_data.get('action_history', []),
					'finalResultResponse': existing_data.get('final_result_response', 'None'),
					'selfReportCompleted': existing_data.get('self_report_completed', False),
					'selfReportSuccess': existing_data.get('self_report_success', None),
					'completeHistory': existing_data.get('complete_history', []),
					'taskDuration': existing_data.get('task_duration'),
					'steps': existing_data.get('steps', 0),
					'tokensUsed': existing_data.get('tokensUsed', 0),
				}
			)
		elif Stage.FORMAT_HISTORY in self.completed_stages:
			formatted_data = self.stage_data[Stage.FORMAT_HISTORY]
			self.server_payload.update(
				{
					'actionHistory': formatted_data.get('action_history', []),
					'finalResultResponse': formatted_data.get('final_result_response', 'None'),
					'selfReportCompleted': formatted_data.get('self_report_completed', False),
					'selfReportSuccess': formatted_data.get('self_report_success', None),
					'completeHistory': formatted_data.get('complete_history', []),
					'taskDuration': formatted_data.get('task_duration'),
					'steps': formatted_data.get('steps', 0),
					'tokensUsed': formatted_data.get('tokensUsed', 0),
				}
			)

		# Update evaluation data if available
		if Stage.EVALUATE in self.completed_stages:
			eval_data = self.stage_data[Stage.EVALUATE]
			judgement = eval_data.get('judgement')
			self.server_payload.update(
				{
					'onlineMind2WebEvaluationJudgement': judgement if judgement is not None else 'None',
					'onlineMind2WebEvaluationError': eval_data.get('error'),
					'onlineMind2WebEvaluationSuccess': eval_data.get('success', False),
					'onlineMind2WebEvaluationScore': eval_data.get('score', 0.0),
				}
			)

		# Update failure states
		self._update_failure_states()

	def _update_failure_states(self):
		"""Update server payload based on failed stages"""
		# Check for browser/execution failures
		for stage, error in self.failed_stages.items():
			if stage in {Stage.SETUP_BROWSER, Stage.RUN_AGENT}:
				self.server_payload['browserCrash'] = True
				if error.error_type == 'timeout':
					self.server_payload['browserCrashReason'] = f'{stage.value} timed out: {error.message}'
				elif error.error_type == 'cancelled':
					self.server_payload['browserCrashReason'] = f'{stage.value} was cancelled: {error.message}'
				else:
					self.server_payload['browserCrashReason'] = f'{stage.value} failed: {error.message}'

			# Update evaluation failures
			elif stage == Stage.EVALUATE:
				if error.error_type == 'timeout':
					self.server_payload['onlineMind2WebEvaluationJudgement'] = 'Evaluation Timed Out'
					self.server_payload['onlineMind2WebEvaluationError'] = 'Evaluation process timed out'
				elif error.error_type == 'cancelled':
					self.server_payload['onlineMind2WebEvaluationJudgement'] = 'Evaluation Cancelled'
					self.server_payload['onlineMind2WebEvaluationError'] = 'Evaluation was cancelled'
				else:
					self.server_payload['onlineMind2WebEvaluationJudgement'] = 'Evaluation Process Error'
					self.server_payload['onlineMind2WebEvaluationError'] = f'Evaluation Error: {error.message}'

	def mark_cancelled(self):
		"""Mark task as cancelled"""
		self.server_payload.update(
			{
				'finalResultResponse': 'Task was cancelled',
				'onlineMind2WebEvaluationJudgement': 'Task Cancelled',
				'onlineMind2WebEvaluationError': 'Task was cancelled',
				'onlineMind2WebEvaluationSuccess': False,
				'onlineMind2WebEvaluationScore': 0.0,
			}
		)
		self.local_error = 'Task cancelled'

	def mark_critical_error(self, error_msg: str):
		"""Mark task as having critical error"""
		self.server_payload.update(
			{
				'finalResultResponse': f'Critical Error: {error_msg}',
				'onlineMind2WebEvaluationJudgement': 'Critical System Error',
				'onlineMind2WebEvaluationError': f'Critical flow error: {error_msg}',
				'onlineMind2WebEvaluationSuccess': False,
				'onlineMind2WebEvaluationScore': 0.0,
			}
		)
		self.local_error = f'Critical flow error: {error_msg}'

	def mark_server_save_failed(self, error_msg: str):
		"""Mark server save as failed"""
		if self.local_error:
			self.local_error += f'; Server save failed: {error_msg}'
		else:
			self.local_error = f'Server save failed: {error_msg}'

	def get_local_status(self) -> dict:
		"""Return local processing status"""
		success = self.execution_succeeded() and (
			Stage.EVALUATE in self.completed_stages or not self.has_execution_data() or Stage.EVALUATE in self.failed_stages
		)
		return {'task_id': self.task_id, 'success': success and not self.local_error, 'error': self.local_error}


async def run_stage(stage: Stage, stage_func, timeout: int | None = None):
	"""Generic stage runner with timeout"""
	if timeout:
		return await asyncio.wait_for(stage_func(), timeout)
	return await stage_func()


async def load_existing_result(task_folder: Path) -> dict:
	"""Load existing result if available"""
	result_file = task_folder / 'result.json'
	if not result_file.exists():
		raise FileNotFoundError('No existing result found')

	async with await anyio.open_file(result_file) as f:
		existing_result = json.loads(await f.read())

	# Check if evaluation is also present
	existing_eval = existing_result.get('Online_Mind2Web_evaluation')
	if existing_eval:
		existing_result['has_evaluation'] = True
		existing_result['evaluation_data'] = existing_eval
	else:
		existing_result['has_evaluation'] = False

	return existing_result


async def setup_browser_session(task: Task, headless: bool) -> BrowserSession:
	"""Setup browser session for the task"""
	logger.debug(f'Browser setup: Creating unique user data directory for task {task.task_id}')
	# Create unique user data directory
	base_user_data_dir = Path(BrowserProfile().user_data_dir).parent
	unique_user_data_dir = base_user_data_dir / f'task_{task.task_id}'
	unique_user_data_dir.mkdir(parents=True, exist_ok=True)

	logger.debug(f'Browser setup: Initializing BrowserSession for task {task.task_id}')
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			user_data_dir=str(unique_user_data_dir),
			headless=headless,
			chromium_sandbox=False,
		),
	)

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
) -> AgentHistoryList:
	"""Run agent with the browser session"""
	# Create controller, optionally with SERP search
	controller = create_controller(use_serp=use_serp)

	# Configure memory if enabled
	memory_config = None
	if enable_memory:
		memory_config = MemoryConfig(agent_id=f'eval_agent_{task.task_id}', memory_interval=memory_interval, llm_instance=llm)

	agent = Agent(
		task=task.confirmed_task,
		llm=llm,
		controller=controller,
		browser_session=browser_session,
		use_vision=use_vision,
		enable_memory=enable_memory,
		memory_config=memory_config,
		max_actions_per_step=max_actions_per_step,
		validate_output=validate_output,
		planner_llm=planner_llm,
		planner_interval=planner_interval,
		source='eval_platform',
	)

	await agent.run(max_steps=max_steps)
	return agent.state.history


async def evaluate_task_result(eval_model: BaseChatModel, task_folder: Path) -> dict:
	"""Evaluate the task result"""
	return await judge_task_result(eval_model, task_folder, score_threshold=3)


def save_result_to_server(convex_url: str, secret_key: str, payload: dict) -> bool:
	"""Save result to server (sync function for use with asyncio.to_thread)"""
	return save_task_result_to_server(convex_url, secret_key, payload)


async def cleanup_browser_safe(browser_session: BrowserSession):
	"""Safe browser cleanup with timeout"""
	try:
		logger.debug('Browser cleanup: Starting close operation for session')
		await asyncio.wait_for(browser_session.close(), timeout=30)
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
	elif Stage.LOAD_EXISTING in completed_stages:
		return Stage.LOAD_EXISTING
	else:
		return Stage.LOAD_EXISTING  # Default starting stage


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
	fresh_start: bool = True,
	use_serp: bool = False,
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
) -> dict:
	"""Clean pipeline approach for running tasks"""
	logger.info(f'Task {task.task_id}: Waiting to acquire semaphore (current value: ~{semaphore_runs._value})')
	async with semaphore_runs:
		logger.info(f'Task {task.task_id}: Semaphore acquired (remaining slots: ~{semaphore_runs._value})')
		task_result = None
		browser_session = None

		try:
			# Initialize task result and basic setup
			task_result = TaskResult(task.task_id, run_id, task.confirmed_task, task, max_steps_per_task)
			task_folder = Path(f'saved_trajectories/{task.task_id}')

			logger.info(f'Task {task.task_id}: Starting execution pipeline.')
			try:
				# Stage 1: Try to load existing result
				try:
					existing_data = await run_stage(Stage.LOAD_EXISTING, lambda: load_existing_result(task_folder))
					task_result.stage_completed(Stage.LOAD_EXISTING, existing_data)

					# If evaluation is also present, mark it as completed
					if existing_data.get('has_evaluation'):
						task_result.stage_completed(Stage.EVALUATE, existing_data['evaluation_data'])

					logger.info(f'Task {task.task_id}: Successfully loaded existing result. Skipping execution.')

				except Exception:
					# No existing result, need to execute full pipeline
					logger.info(f'Task {task.task_id}: No existing result found. Starting execution pipeline.')

					agent_history = None  # Initialize to track agent execution

					# Stage 2: Setup browser
					try:
						logger.info(f'Task {task.task_id}: Browser setup starting.')
						browser_session = await run_stage(
							Stage.SETUP_BROWSER, lambda: setup_browser_session(task, headless), timeout=120
						)
						task_result.stage_completed(Stage.SETUP_BROWSER)
						logger.info(f'Task {task.task_id}: Browser session started successfully.')
					except Exception as e:
						error = StageError(Stage.SETUP_BROWSER, 'exception', str(e))
						task_result.stage_failed(Stage.SETUP_BROWSER, error)
						logger.error(f'Task {task.task_id}: Browser setup failed: {str(e)}')
						# Continue to server save instead of early return

					# Stage 3: Run agent
					if browser_session:  # Only run agent if browser setup succeeded
						try:
							logger.info(f'Task {task.task_id}: Agent run starting.')
							agent_history = await run_stage(
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
								timeout=600,
							)
							task_result.stage_completed(Stage.RUN_AGENT)
							logger.info(f'Task {task.task_id}: Agent run completed.')
						except Exception as e:
							error = StageError(Stage.RUN_AGENT, 'exception', str(e))
							task_result.stage_failed(Stage.RUN_AGENT, error)
							logger.error(f'Task {task.task_id}: Agent run failed: {str(e)}')
							# Continue to server save instead of early return

					# Stage 4: Format history
					if agent_history is not None:  # Only format if agent ran successfully
						try:
							logger.info(f'Task {task.task_id}: History formatting starting.')
							formatted_data = await run_stage(
								Stage.FORMAT_HISTORY,
								lambda: reformat_agent_history(agent_history, task.task_id, run_id, task.confirmed_task),
							)
							task_result.stage_completed(Stage.FORMAT_HISTORY, formatted_data)
							logger.info(f'Task {task.task_id}: Agent history formatted.')
						except Exception as e:
							error = StageError(Stage.FORMAT_HISTORY, 'exception', str(e))
							task_result.stage_failed(Stage.FORMAT_HISTORY, error)
							logger.error(f'Task {task.task_id}: History formatting failed: {str(e)}')
							# Continue to server save instead of early return

				# Stage 5: Evaluate (if we have execution data and no existing evaluation)
				if task_result.has_execution_data() and Stage.EVALUATE not in task_result.completed_stages:
					try:
						logger.info(f'Task {task.task_id}: Evaluation starting.')
						evaluation = await run_stage(
							Stage.EVALUATE, lambda: evaluate_task_result(eval_model, task_folder), timeout=300
						)
						task_result.stage_completed(Stage.EVALUATE, evaluation)
						logger.info(f'Task {task.task_id}: Evaluation completed.')
					except Exception as e:
						error = StageError(Stage.EVALUATE, 'exception', str(e))
						task_result.stage_failed(Stage.EVALUATE, error)
						logger.error(f'Task {task.task_id}: Evaluation failed: {str(e)}')

				# Stage 6: Save to server (always attempt)
				try:
					logger.info(f'Task {task.task_id}: Saving result to server.')
					await run_stage(
						Stage.SAVE_SERVER,
						lambda: asyncio.to_thread(save_result_to_server, convex_url, secret_key, task_result.server_payload),
						timeout=60,
					)
					task_result.stage_completed(Stage.SAVE_SERVER)
					logger.info(f'Task {task.task_id}: Successfully saved result to server.')
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
						lambda: asyncio.to_thread(save_result_to_server, convex_url, secret_key, task_result.server_payload),
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
						lambda: asyncio.to_thread(save_result_to_server, convex_url, secret_key, task_result.server_payload),
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
						lambda: asyncio.to_thread(save_result_to_server, convex_url, secret_key, task_result.server_payload),
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
					task_result = TaskResult(task.task_id, run_id, task.confirmed_task, task, max_steps_per_task)
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
				await asyncio.to_thread(save_result_to_server, convex_url, secret_key, task_result.server_payload)
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

		logger.info(f'Task {task.task_id}: About to release semaphore (remaining slots: ~{semaphore_runs._value})')
		return (
			task_result.get_local_status()
			if task_result
			else {'task_id': task.task_id, 'success': False, 'error': 'Task result not available'}
		)


async def run_multiple_tasks(
	tasks: list[Task],
	llm: BaseChatModel,
	run_id: str,
	convex_url: str,
	secret_key: str,
	eval_model: BaseChatModel,
	max_parallel_runs: int = 3,
	max_steps_per_task: int = 25,
	start_index: int = 0,
	end_index: int | None = None,
	headless: bool = False,
	use_vision: bool = True,
	fresh_start: bool = True,
	use_serp: bool = False,
	enable_memory: bool = False,
	memory_interval: int = 10,
	max_actions_per_step: int = 10,
	validate_output: bool = False,
	planner_llm: BaseChatModel | None = None,
	planner_interval: int = 1,
) -> dict:
	"""
	Run multiple tasks in parallel and evaluate results.
	"""
	logger.info(f'Creating semaphore with max_parallel_runs={max_parallel_runs}')
	semaphore_runs = asyncio.Semaphore(max_parallel_runs)
	tasks_to_run = tasks[start_index:end_index] if end_index else tasks[start_index:]

	logger.info(f'Starting {len(tasks_to_run)} tasks with parallel limit of {max_parallel_runs}')

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
				fresh_start=fresh_start,
				use_serp=use_serp,
				enable_memory=enable_memory,
				memory_interval=memory_interval,
				max_actions_per_step=max_actions_per_step,
				validate_output=validate_output,
				planner_llm=planner_llm,
				planner_interval=planner_interval,
			)
			for task in tasks_to_run
		),
		return_exceptions=True,  # Prevent task cancellation cascade
	)

	# Process task results and handle any exceptions returned by gather
	processed_results = []
	successful_tasks = 0
	failed_tasks = 0

	for i, result in enumerate(task_results):
		if isinstance(result, Exception):
			logger.error(f'Task {i} failed with exception: {type(result).__name__}: {result}')
			processed_results.append({'task_id': f'task_{i}', 'success': False, 'error': str(result)})
			failed_tasks += 1
		else:
			processed_results.append(result)
			if result.get('success', False):
				successful_tasks += 1
			else:
				failed_tasks += 1

	logger.info(f'All {len(tasks_to_run)} tasks completed. Success: {successful_tasks}, Failed: {failed_tasks}')

	# After all tasks are complete, calculate a local summary
	logger.info('All tasks completed. Calculating result summary...')
	summary = calculate_local_summary()

	# Log the summary statistics
	logger.info(f'Completed {summary["total_tasks"]} tasks')
	logger.info(f'Success rate: {summary["success_rate"]:.2%}')
	logger.info(f'Average score: {summary["average_score"]:.2f}')

	return {'task_results': processed_results, 'summary': summary}


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
	parser.add_argument('--parallel-runs', type=int, default=3, help='Number of parallel tasks to run')
	parser.add_argument('--max-steps', type=int, default=25, help='Maximum steps per task')
	parser.add_argument('--start', type=int, default=0, help='Start index')
	parser.add_argument('--end', type=int, default=None, help='End index (exclusive)')
	parser.add_argument('--headless', action='store_true', help='Run in headless mode')
	parser.add_argument('--evaluate-only', action='store_true', help='Only evaluate existing results without running new tasks')
	parser.add_argument(
		'--model', type=str, default='gpt-4o', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for the agent'
	)
	parser.add_argument(
		'--eval-model', type=str, default='gpt-4o', choices=list(SUPPORTED_MODELS.keys()), help='Model to use for evaluation'
	)
	parser.add_argument('--no-vision', action='store_true', help='Disable vision capabilities in the agent')
	parser.add_argument(
		'--fresh-start',
		type=lambda x: (str(x).lower() == 'true'),
		default=True,
		help='Clear saved_trajectories before starting. Set to False to keep existing trajectories (default: True)',
	)
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
		except TypeError as e:
			logger.error(
				f'Error creating Task objects from fetched data. Ensure the data structure includes required fields (task_id, confirmed_task). Optional fields: website, reference_length, level, cluster_id. Error: {type(e).__name__}: {e}'
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
			'start_index': args.start,
			'end_index': args.end,
			'headless': args.headless,
			'use_vision': not args.no_vision,
			'task_source': args.test_case,
			'llm_judge': args.eval_model,
		}

		run_data = {
			'model': args.model,
			'gitBranch': git_info['branch'],
			'gitCommitHash': git_info['hash'],
			'gitCommitTimestamp': git_info['timestamp'],
			'userMessage': args.user_message,
			'evalGroup': args.eval_group,
			'developerId': args.developer_id,
			'totalTasks': len(tasks) - args.start if args.end is None else args.end - args.start,
			'testCaseName': args.test_case,
			'additionalData': additional_run_data,
		}

		run_id = start_new_run(CONVEX_URL, SECRET_KEY, run_data)

		if not run_id:
			logger.error('Failed to start a new run on the server. Exiting.')
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

		results = asyncio.run(
			run_multiple_tasks(
				tasks=tasks,
				llm=llm,
				run_id=run_id,
				convex_url=CONVEX_URL,
				secret_key=SECRET_KEY,
				eval_model=eval_model,
				max_parallel_runs=args.parallel_runs,
				max_steps_per_task=args.max_steps,
				start_index=args.start,
				end_index=args.end,
				headless=args.headless,
				use_vision=not args.no_vision,
				fresh_start=args.fresh_start,
				use_serp=args.use_serp,
				enable_memory=args.enable_memory,
				memory_interval=args.memory_interval,
				max_actions_per_step=args.max_actions_per_step,
				validate_output=args.validate_output,
				planner_llm=planner_llm,
				planner_interval=args.planner_interval,
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
