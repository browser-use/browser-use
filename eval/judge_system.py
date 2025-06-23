"""
@file purpose: Comprehensive judge system for evaluating browser-use agent runs with detailed structured feedback.

This system provides multi-dimensional evaluation of agent performance including:
- Task analysis and categorization
- Trajectory quality assessment
- Tool usage effectiveness
- Agent reasoning quality
- Browser handling capabilities
- Structured error categorization
- Actionable improvement suggestions

The judge uses vision-language models to analyze agent execution history, screenshots,
and final results to provide detailed structured JSON feedback for developers.
"""

import asyncio
import base64
import io
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from PIL import Image

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
	# Access & Authentication
	BLOCKED_ACCESS = 'blocked_access'
	CAPTCHA_CHALLENGE = 'captcha_challenge'
	LOGIN_REQUIRED = 'login_required'
	RATE_LIMITED = 'rate_limited'

	# Tool & Action Failures
	TOOL_MISUSE = 'tool_misuse'
	INVALID_PARAMETERS = 'invalid_parameters'
	ACTION_SEQUENCE_ERROR = 'action_sequence_error'

	# Agent Behavior Issues
	INFINITE_LOOP = 'infinite_loop'
	STUCK_PATTERN = 'stuck_pattern'
	POOR_PLANNING = 'poor_planning'
	CONTEXT_LOSS = 'context_loss'

	# Browser & Technical
	ELEMENT_NOT_FOUND = 'element_not_found'
	CLICK_FAILURE = 'click_failure'
	LOAD_TIMEOUT = 'load_timeout'
	JAVASCRIPT_ERROR = 'javascript_error'

	# Content & Understanding
	MISUNDERSTOOD_TASK = 'misunderstood_task'
	FORMAT_ERROR = 'format_error'
	CONTENT_PARSING_ERROR = 'content_parsing_error'

	# Enhanced Detection Categories
	NAVIGATION_CONFUSION = 'navigation_confusion'
	FORM_FILLING_ERROR = 'form_filling_error'
	MODAL_HANDLING = 'modal_handling'
	IFRAME_ISSUES = 'iframe_issues'
	BROWSER_CRASHES = 'browser_crashes'
	IMPOSSIBLE_TASK = 'impossible_task'
	MISSING_INFORMATION = 'missing_information'


class TaskCategory(Enum):
	EXTRACTION = 'extraction'
	INTERACTION = 'interaction'
	LOGIN = 'login'
	RESEARCH = 'research'
	SHOPPING = 'shopping'
	BOOKING = 'booking'
	COMPARISON = 'comparison'
	QA_TESTING = 'qa_testing'
	FORM_FILLING = 'form_filling'
	NAVIGATION = 'navigation'
	SEARCH = 'search'
	FILTERING = 'filtering'
	CONTENT_CREATION = 'content_creation'
	FILE_OPERATIONS = 'file_operations'
	MULTI_STEP_WORKFLOW = 'multi_step_workflow'


@dataclass
class ScoreBreakdown:
	trajectory_quality: int  # How human-like is the solution path (1-100)
	tool_calling_effectiveness: int  # How well do tools work (1-100)
	agent_reasoning: int  # Quality of agent's decision making (1-100)
	browser_handling: int  # Browser stability and error handling (1-100)
	task_satisfaction: int  # Final user satisfaction (1-100)


@dataclass
class JudgeResult:
	# Basic Information
	task_summary: str  # 1 sentence summary
	task_clarity_score: int  # How clear vs uncertain the task is (1-100)
	task_categories: list[TaskCategory]  # Primary task categories

	# Analysis
	reasoning: str  # What went well/not well analysis
	error_categories: list[ErrorCategory]  # Core error categories identified

	# Scores
	scores: ScoreBreakdown
	final_score: int  # Overall score (1-100)
	passed: bool  # Whether it meets 70% threshold

	# Developer Feedback
	improvement_tips: list[str]  # Concrete improvement suggestions
	critical_issues: list[str]  # Must-fix issues

	# Metadata
	evaluation_timestamp: str


def encode_image(image_path: str) -> str:
	"""Convert image file to base64 string."""
	try:
		with Image.open(image_path) as image:
			if image.mode == 'RGBA':
				image = image.convert('RGB')
			buffered = io.BytesIO()
			image.save(buffered, format='JPEG')
			return base64.b64encode(buffered.getvalue()).decode('utf-8')
	except Exception as e:
		logger.error(f'Failed to encode image {image_path}: {e}')
		return ''


def truncate_text(text: str, max_length: int) -> str:
	"""Truncate text to maximum length with ellipsis."""
	if len(text) <= max_length:
		return text
	return text[: max_length - 3] + '...'


def prepare_agent_steps(complete_history: list[dict]) -> list[str]:
	"""Extract and format agent steps, limiting each to 2000 characters."""
	steps = []
	for i, step in enumerate(complete_history):
		step_text = f'Step {i + 1}:\n'

		# Add model output if available
		if step.get('model_output'):
			model_output = step['model_output']
			if isinstance(model_output, dict):
				# Format the model output nicely
				if 'action' in model_output:
					step_text += f'Actions: {json.dumps(model_output["action"], indent=1)}\n'
				if 'current_state' in model_output:
					step_text += f'State: {model_output["current_state"]}\n'

		# Add results if available
		if step.get('result'):
			for j, result in enumerate(step['result']):
				if isinstance(result, dict):
					if result.get('extracted_content'):
						step_text += f'Result {j + 1}: {result["extracted_content"]}\n'
					if result.get('error'):
						step_text += f'Error {j + 1}: {result["error"]}\n'

		# Add URL info
		if step.get('state', {}).get('url'):
			step_text += f'URL: {step["state"]["url"]}\n'

		# Truncate to 2000 characters
		steps.append(truncate_text(step_text, 2000))

	return steps


async def comprehensive_judge(
	task: str,
	complete_history: list[dict],
	final_result: str,
	screenshot_paths: list[str],
	model: BaseChatModel,
	max_images: int = 10,
) -> JudgeResult:
	"""
	Comprehensive judge that evaluates browser-use agent runs with detailed structured feedback.
	"""

	# Prepare inputs with length limits
	task_truncated = truncate_text(task, 40000)
	final_result_truncated = truncate_text(final_result or 'No final result', 40000)
	agent_steps = prepare_agent_steps(complete_history)

	# Select last N images
	selected_images = screenshot_paths[-max_images:] if screenshot_paths else []

	# Encode images
	encoded_images = []
	for img_path in selected_images:
		if Path(img_path).exists():
			encoded_img = encode_image(img_path)
			if encoded_img:
				encoded_images.append(
					{
						'type': 'image_url',
						'image_url': {
							'url': f'data:image/jpeg;base64,{encoded_img}',
							'detail': 'high',
						},
					}
				)

	# Construct the evaluation prompt
	system_prompt = """You are an expert judge evaluating browser automation agent performance. 

Your task is to comprehensively analyze the agent's execution and provide structured feedback.

**EVALUATION CRITERIA:**

1. **Task Analysis**: Understand what the user wanted to accomplish
2. **Trajectory Quality**: How human-like and efficient was the solution path?
3. **Tool Usage**: How effectively were browser automation tools used?
4. **Agent Reasoning**: Quality of decision-making and problem-solving
5. **Browser Handling**: How well were browser issues handled?
6. **Final Outcome**: Did the task satisfy the user's intent?

**ERROR CATEGORIES TO CONSIDER:**
- Access & Authentication: blocked_access, captcha_challenge, login_required, rate_limited
- Tool & Action Failures: tool_misuse, invalid_parameters, action_sequence_error
- Agent Behavior: infinite_loop, stuck_pattern, poor_planning, context_loss
- Browser & Technical: element_not_found, click_failure, load_timeout, javascript_error
- Content & Understanding: misunderstood_task, format_error, content_parsing_error
- Enhanced: navigation_confusion, form_filling_error, modal_handling, iframe_issues, browser_crashes, impossible_task, missing_information


**TASK CATEGORIES TO CONSIDER:**
extraction, interaction, login, research, shopping, booking, comparison, qa_testing, form_filling, navigation, search, filtering, content_creation, file_operations, multi_step_workflow
- You can use multiple categories for the same task.
- You can also add other categories if they fit better.

**TASK CLARITY SCORE:**
- is the task very clear step by step like a recipe (high score) or very vague and uncertain (low score)

**IMPROVEMENT TIPS:**
- Think how to get this task done better. Create actionable tips - but they should be understandable for a developer who does not know the task.
- These tips will be avg across many tasks and then the most common / problemetic will be used to improve the browser-use agent.
- In browser-use we convert websites to text so that the agent can understand it. In there we mark interactive elements with [index] and then the agent can chose to interact with them and we click then the actual css selector. Sometimes this conversion is not perfect.
- After the agent takes an action it gets the new state and its previous thinking, and outputs the next action. Which we then execute again.
- So we can improve the agent system prompt, input context, tool calls to interact with the browser, or our extraction layer to convert the website to text.
- always first mention the error this would fix and then the improvement tip.

**SCORING SCALE:**
- 90-100: Excellent execution, human-like, minimal issues
- 80-89: Good execution with minor issues
- 70-79: Acceptable execution, some problems but functional
- 60-69: Poor execution with significant issues
- 1-59: Failed execution, major problems

**PASS THRESHOLD: 70%**

Respond with EXACTLY this JSON structure (no additional text):

{
    "task_summary": "One sentence summary of what the task was trying to accomplish",
    "task_categories": ["category1", "category2"],
    "task_clarity_score": 85,
    "reasoning": "Detailed analysis of what went well and what didn't, trajectory quality, planning assessment",
    "error_categories": ["error1", "error2"],
    "scores": {
        "trajectory_quality": 75,
        "tool_calling_effectiveness": 80,
        "agent_reasoning": 85,
        "browser_handling": 65,
        "task_satisfaction": 70
    },
    "final_score": 75,
    "critical_issues": [
        "Critical issue that must be fixed 1",
        "Critical issue that must be fixed 2"
    ],
    "improvement_tips": [
        "Specific actionable improvement 1",
        "Specific actionable improvement 2"
    ]
}"""

	user_prompt = f"""**TASK:** {task_truncated}

**AGENT EXECUTION STEPS:**
{chr(10).join(agent_steps)}

**FINAL RESULT:**
{final_result_truncated}

**TOTAL STEPS:** {len(complete_history)}
**SCREENSHOTS PROVIDED:** {len(selected_images)}

Analyze this execution and respond with the exact JSON structure requested."""

	# Build messages
	content_parts = [{'type': 'text', 'text': user_prompt}]
	content_parts.extend(encoded_images)

	messages = [
		{'role': 'system', 'content': system_prompt},
		{'role': 'user', 'content': content_parts},
	]

	# Get structured response
	try:
		response = await asyncio.to_thread(model.invoke, messages)

		# Parse the JSON response
		# Handle both string and list content types
		if isinstance(response.content, list):
			response_text = str(response.content[0]) if response.content else ''
		else:
			response_text = str(response.content)
		response_text = response_text.strip()

		# Try to extract JSON if wrapped in markdown
		if '```json' in response_text:
			json_start = response_text.find('```json') + 7
			json_end = response_text.find('```', json_start)
			if json_end != -1:
				response_text = response_text[json_start:json_end].strip()
		elif '```' in response_text:
			json_start = response_text.find('```') + 3
			json_end = response_text.find('```', json_start)
			if json_end != -1:
				response_text = response_text[json_start:json_end].strip()

		# Parse JSON
		try:
			result_dict = json.loads(response_text)
		except json.JSONDecodeError as e:
			logger.error(f'Failed to parse JSON response: {e}')
			logger.error(f'Response text: {response_text}')
			# Create fallback result
			return create_fallback_result(task, 'Failed to parse judge response')

		# Convert to structured result
		return parse_judge_response(result_dict, task)

	except Exception as e:
		logger.error(f'Judge evaluation failed: {e}')
		return create_fallback_result(task, str(e))


def parse_judge_response(result_dict: dict, task: str) -> JudgeResult:
	"""Parse the LLM response into a structured JudgeResult."""
	try:
		# Parse task categories
		task_categories = []
		if 'task_categories' in result_dict:
			for cat in result_dict['task_categories']:
				try:
					task_categories.append(TaskCategory(cat))
				except ValueError:
					logger.warning(f'Unknown task category: {cat}')

		# Parse error categories
		error_categories = []
		if 'error_categories' in result_dict:
			for err in result_dict['error_categories']:
				try:
					error_categories.append(ErrorCategory(err))
				except ValueError:
					logger.warning(f'Unknown error category: {err}')

		# Parse scores
		scores_dict = result_dict.get('scores', {})
		scores = ScoreBreakdown(
			trajectory_quality=scores_dict.get('trajectory_quality', 50),
			tool_calling_effectiveness=scores_dict.get('tool_calling_effectiveness', 50),
			agent_reasoning=scores_dict.get('agent_reasoning', 50),
			browser_handling=scores_dict.get('browser_handling', 50),
			task_satisfaction=scores_dict.get('task_satisfaction', 50),
		)

		final_score = result_dict.get('final_score', 50)

		return JudgeResult(
			task_summary=result_dict.get('task_summary', 'Task analysis unavailable'),
			task_clarity_score=result_dict.get('task_clarity_score', 50),
			task_categories=task_categories,
			reasoning=result_dict.get('reasoning', 'Analysis unavailable'),
			error_categories=error_categories,
			scores=scores,
			final_score=final_score,
			passed=final_score >= 70,
			improvement_tips=result_dict.get('improvement_tips', []),
			critical_issues=result_dict.get('critical_issues', []),
			evaluation_timestamp=datetime.now().isoformat(),
		)

	except Exception as e:
		logger.error(f'Failed to parse judge response: {e}')
		return create_fallback_result(task, 'Failed to parse structured response')


def create_fallback_result(task: str, error_msg: str) -> JudgeResult:
	"""Create a fallback result when evaluation fails."""
	return JudgeResult(
		task_summary=f'Failed to analyze task: {task[:100]}...',
		task_clarity_score=0,
		task_categories=[TaskCategory.QA_TESTING],
		reasoning=f'Evaluation failed: {error_msg}',
		error_categories=[ErrorCategory.IMPOSSIBLE_TASK],
		scores=ScoreBreakdown(
			trajectory_quality=0,
			tool_calling_effectiveness=0,
			agent_reasoning=0,
			browser_handling=0,
			task_satisfaction=0,
		),
		final_score=0,
		passed=False,
		improvement_tips=['Fix evaluation system'],
		critical_issues=[f'Evaluation system failure: {error_msg}'],
		evaluation_timestamp=datetime.now().isoformat(),
	)


async def judge_with_retry(
	task: str,
	complete_history: list[dict],
	final_result: str,
	screenshot_paths: list[str],
	model: BaseChatModel,
	max_retries: int = 3,
	max_images: int = 10,
) -> JudgeResult:
	"""
	Judge with retry logic for robustness.
	"""
	for attempt in range(max_retries):
		try:
			return await comprehensive_judge(
				task,
				complete_history,
				final_result,
				screenshot_paths,
				model,
				max_images,
			)
		except Exception as e:
			if attempt == max_retries - 1:
				logger.error(f'Judge failed after {max_retries} attempts: {e}')
				return create_fallback_result(task, str(e))
			logger.warning(f'Judge attempt {attempt + 1} failed, retrying: {e}')
			await asyncio.sleep(2**attempt)

	# Fallback return (should never reach here given the logic above, but ensures type safety)
	return create_fallback_result(task, 'Max retries exceeded without proper error handling')


def get_example_json_structure() -> dict:
	"""Get an example of the expected JSON response structure for the LLM judge."""
	return {
		'task_summary': 'Extract product prices from an e-commerce website',
		'task_clarity_score': 85,
		'task_categories': ['extraction', 'research'],
		'reasoning': 'The agent successfully navigated to the target website and extracted most product information. However, it had difficulty with dynamic loading elements and missed some prices that loaded asynchronously. The overall approach was logical but could benefit from better wait strategies.',
		'error_categories': ['element_not_found', 'load_timeout'],
		'scores': {
			'trajectory_quality': 75,
			'tool_calling_effectiveness': 80,
			'agent_reasoning': 85,
			'browser_handling': 65,
			'task_satisfaction': 70,
		},
		'final_score': 75,
		'critical_issues': [
			'Missing wait for dynamic content to load',
			'No fallback strategy when primary selectors fail',
		],
		'improvement_tips': [
			'Browser not loaded: Implement better wait strategies for dynamic content',
			'Element not found: Add retry logic for element detection',
			'No error message: Improve error handling for the tool click element',
		],
	}


def _read_result_file(result_file: Path) -> dict[str, Any]:
	"""Helper function to read result file synchronously."""
	with open(result_file) as f:
		return json.load(f)


def _write_result_file(result_file: Path, result_data: dict[str, Any]) -> None:
	"""Helper function to write result file synchronously."""
	with open(result_file, 'w') as f:
		f.write(json.dumps(result_data, indent=2, default=str))


# Integration helper function
async def evaluate_task_with_comprehensive_judge(task_folder: Path, model: BaseChatModel, max_images: int = 10) -> dict[str, Any]:
	"""
	Evaluate a task result using the comprehensive judge system.

	Returns a dictionary with both the old format for compatibility
	and the new comprehensive analysis.
	"""
	result_file = task_folder / 'result.json'
	if not result_file.exists():
		return {
			'task_id': task_folder.name,
			'comprehensive_judge': None,
			'error': 'No result.json found',
		}

	try:
		# Load existing result using async wrapper
		result_data = await asyncio.to_thread(_read_result_file, result_file)

		# Check if comprehensive judge result already exists
		if result_data.get('comprehensive_judge_evaluation'):
			return {
				'task_id': task_folder.name,
				'comprehensive_judge': result_data['comprehensive_judge_evaluation'],
				'error': None,
			}

		# Extract data for evaluation
		task = result_data.get('task', 'Unknown task')
		complete_history = result_data.get('complete_history', [])
		final_result = result_data.get('final_result_response', '')
		screenshot_paths = result_data.get('screenshot_paths', [])

		# Run comprehensive evaluation
		judge_result = await judge_with_retry(
			task=task,
			complete_history=complete_history,
			final_result=final_result,
			screenshot_paths=screenshot_paths,
			model=model,
			max_images=max_images,
		)

		# Convert to dict for storage
		judge_dict = asdict(judge_result)

		# Save back to result file using async wrapper
		result_data['comprehensive_judge_evaluation'] = judge_dict
		await asyncio.to_thread(_write_result_file, result_file, result_data)

		return {
			'task_id': task_folder.name,
			'comprehensive_judge': judge_dict,
			'error': None,
		}

	except Exception as e:
		logger.error(f'Comprehensive judge evaluation failed for {task_folder.name}: {e}')
		return {
			'task_id': task_folder.name,
			'comprehensive_judge': None,
			'error': str(e),
		}
