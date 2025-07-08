import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from eval.utils import create_pydantic_model_from_schema, make_json_serializable

logger = logging.getLogger(__name__)


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
	github_workflow_url: str | None = None
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
			'githubWorkflowUrl': self.github_workflow_url,
		}

		# Add task execution data if available
		if Stage.FORMAT_HISTORY in self.completed_stages:
			format_data = self.stage_data.get(Stage.FORMAT_HISTORY, {})
			logger.info(f'format_data: {format_data}')
			# log token usage
			logger.info(f'tokensUsed: {format_data.get("tokensUsed")}')
			logger.info(f'usage: {format_data.get("usage")}')

			# Handle usage data - convert to JSON string if it's a dict
			usage_data = format_data.get('usage')
			if usage_data and isinstance(usage_data, dict):
				usage_data = json.dumps(usage_data)

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
					'usage': usage_data,  # Add usage data (JSON string if dict)
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
		self.auth_keys = kwargs.get('auth_keys', None)  # List of auth keys to fetch from auth distribution
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
			'auth_keys',
		}
		self.additional_fields = {k: v for k, v in kwargs.items() if k not in known_fields}

		# Make all additional fields accessible as attributes
		for key, value in self.additional_fields.items():
			setattr(self, key, value)

	def __str__(self):
		# Include main fields and indicate if there are additional fields
		base_str = f'Task(task_id={self.task_id}, confirmed_task={self.confirmed_task}, website={self.website}, reference_length={self.reference_length}, level={self.level}, cluster_id={self.cluster_id}, login_cookie={self.login_cookie}, login_type={self.login_type}, category={self.category}, output_schema={self.output_schema}, auth_keys={self.auth_keys}'
		if self.additional_fields:
			additional_str = ', '.join(f'{k}={v}' for k, v in self.additional_fields.items())
			base_str += f', {additional_str}'
		base_str += ')'
		return base_str

	def __repr__(self):
		return self.__str__()
