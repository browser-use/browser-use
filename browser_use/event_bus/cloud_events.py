"""
Cloud-specific events designed to sync with the cloud backend database models.

These events map directly to the SQLModel schemas:
- AgentSessionModel
- AgentTaskModel
- AgentStepModel
- UserUploadedFileModel
- AgentOutputFileModel
"""

from typing import Any, Literal

from pydantic import Field
from uuid_extensions import uuid7str

from browser_use.event_bus.views import Event


# Session lifecycle events
class SessionStartedEvent(Event):
	"""Emitted when a browser session starts"""

	session_id: str = Field(default_factory=uuid7str)
	user_id: str
	browser_type: Literal['chrome', 'firefox', 'safari', 'edge'] = 'chrome'
	browser_version: str | None = None
	window_width: int = 1280
	window_height: int = 720
	user_agent: str | None = None
	proxy_url: str | None = None
	headless: bool = True
	initial_url: str | None = None
	context_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionStoppedEvent(Event):
	"""Emitted when a browser session stops"""

	session_id: str
	reason: Literal['completed', 'error', 'timeout', 'user_cancelled'] = 'completed'
	error_message: str | None = None
	total_duration_seconds: float
	total_input_tokens: int = 0
	total_output_tokens: int = 0
	total_cost_usd: float = 0.0


class SessionBrowserStateUpdatedEvent(Event):
	"""Emitted when browser state changes (URL, tabs, etc)"""

	session_id: str
	current_url: str
	current_title: str | None = None
	active_tab_id: int
	total_tabs: int
	tabs_info: list[dict[str, Any]] = Field(default_factory=list)  # TabInfo serialized


# Task lifecycle events
class TaskStartedEvent(Event):
	"""Emitted when a new task starts within a session"""

	task_id: str = Field(default_factory=uuid7str)
	session_id: str
	task_description: str
	task_type: Literal['extraction', 'action', 'navigation', 'monitoring', 'other'] = 'other'
	max_steps: int = 100
	priority: Literal['low', 'medium', 'high'] = 'medium'
	parent_task_id: str | None = None
	context_data: dict[str, Any] = Field(default_factory=dict)


class TaskCompletedEvent(Event):
	"""Emitted when a task completes"""

	task_id: str
	session_id: str
	status: Literal['completed', 'failed', 'cancelled', 'timeout'] = 'completed'
	success: bool = True
	result_summary: str | None = None
	extracted_data: dict[str, Any] | None = None
	error_message: str | None = None
	duration_seconds: float
	total_steps: int
	input_tokens: int = 0
	output_tokens: int = 0
	cost_usd: float = 0.0


class TaskPausedEvent(Event):
	"""Emitted when a task is paused"""

	task_id: str
	session_id: str
	reason: str | None = None
	can_resume: bool = True
	checkpoint_data: dict[str, Any] = Field(default_factory=dict)


class TaskResumedEvent(Event):
	"""Emitted when a paused task is resumed"""

	task_id: str
	session_id: str
	checkpoint_data: dict[str, Any] = Field(default_factory=dict)


class TaskStoppedEvent(Event):
	"""Emitted when a task is stopped"""

	task_id: str


class StepCreatedEvent(Event):
	"""Emitted when a step is created"""

	step_id: str
	agent_task_id: str
	step: int
	evaluation_previous_goal: str
	memory: str
	next_goal: str
	actions: list[dict[str, Any]]
	screenshot_url: str
	url: str


class TaskUserFeedbackEvent(Event):
	"""Emitted when user provides feedback on a task"""

	task_id: str
	user_feedback_type: str
	user_comment: str | None = None


class SessionBrowserDataUpdatedEvent(Event):
	"""Emitted when browser session data is updated"""

	session_id: str
	browser_session_data: dict[str, Any]


# Step events with evaluation data
class StepExecutedEvent(Event):
	"""Emitted when a step is executed with full evaluation data"""

	step_id: str = Field(default_factory=uuid7str)
	task_id: str
	session_id: str
	step_number: int

	# Action data
	action_type: str
	action_params: dict[str, Any] = Field(default_factory=dict)
	target_element_index: int | None = None
	target_element_selector: str | None = None
	target_element_attributes: dict[str, Any] = Field(default_factory=dict)

	# Evaluation data (from AgentBrain)
	evaluation_previous_goal: str
	memory: str
	next_goal: str

	# Results
	success: bool = True
	error_message: str | None = None
	extracted_content: str | None = None

	# Browser state
	url_before: str
	url_after: str
	screenshot_before: str | None = None
	screenshot_after: str | None = None
	dom_changes_summary: str | None = None

	# Performance
	duration_ms: float
	llm_latency_ms: float | None = None
	browser_latency_ms: float | None = None

	# Model info
	model_name: str
	prompt_tokens: int = 0
	completion_tokens: int = 0
	model_cost_usd: float = 0.0


class StepScreenshotTakenEvent(Event):
	"""Emitted when a screenshot is taken during a step"""

	step_id: str
	task_id: str
	session_id: str
	screenshot_type: Literal['before_action', 'after_action', 'error', 'validation'] = 'before_action'
	screenshot_base64: str
	screenshot_size_bytes: int
	viewport_width: int
	viewport_height: int
	full_page: bool = False


# File events
class UserFileUploadedEvent(Event):
	"""Emitted when a user uploads a file"""

	file_id: str = Field(default_factory=uuid7str)
	user_id: str
	session_id: str | None = None
	task_id: str | None = None

	filename: str
	mime_type: str
	size_bytes: int
	storage_path: str
	is_public: bool = False
	metadata: dict[str, Any] = Field(default_factory=dict)


class OutputFileGeneratedEvent(Event):
	"""Emitted when the agent generates an output file"""

	file_id: str = Field(default_factory=uuid7str)
	task_id: str
	session_id: str
	step_id: str | None = None

	filename: str
	mime_type: str
	size_bytes: int
	storage_path: str
	file_type: Literal['screenshot', 'data_export', 'report', 'log', 'other'] = 'other'
	content_preview: str | None = None
	metadata: dict[str, Any] = Field(default_factory=dict)


# User feedback events
class UserFeedbackProvidedEvent(Event):
	"""Emitted when user provides feedback on a task or step"""

	feedback_id: str = Field(default_factory=uuid7str)
	user_id: str
	session_id: str | None = None
	task_id: str | None = None
	step_id: str | None = None

	feedback_type: Literal['rating', 'correction', 'comment', 'report'] = 'comment'
	rating: int | None = None  # 1-5 scale
	feedback_text: str | None = None
	corrected_data: dict[str, Any] | None = None
	tags: list[str] = Field(default_factory=list)


# Error and monitoring events
class ErrorTrackedEvent(Event):
	"""Emitted when an error occurs that should be tracked"""

	error_id: str = Field(default_factory=uuid7str)
	session_id: str | None = None
	task_id: str | None = None
	step_id: str | None = None

	error_type: str
	error_message: str
	error_code: str | None = None
	stack_trace: str | None = None
	severity: Literal['low', 'medium', 'high', 'critical'] = 'medium'
	recoverable: bool = True
	context_data: dict[str, Any] = Field(default_factory=dict)


class PerformanceMetricEvent(Event):
	"""Emitted to track performance metrics"""

	session_id: str
	task_id: str | None = None

	metric_name: str
	metric_value: float
	metric_unit: str
	tags: dict[str, str] = Field(default_factory=dict)

	# Common metrics
	page_load_time_ms: float | None = None
	dom_processing_time_ms: float | None = None
	llm_response_time_ms: float | None = None
	total_memory_mb: float | None = None
	cpu_usage_percent: float | None = None


# Webhook/notification events
class WebhookTriggeredEvent(Event):
	"""Emitted when a condition triggers a webhook notification"""

	webhook_id: str
	session_id: str
	task_id: str | None = None

	trigger_type: str
	condition_met: str
	payload: dict[str, Any] = Field(default_factory=dict)
	notification_sent: bool = False
	response_status: int | None = None


# Analytics events
class TaskAnalyticsEvent(Event):
	"""Aggregated analytics for a completed task"""

	task_id: str
	session_id: str

	# Success metrics
	success_rate: float
	steps_to_completion: int
	retry_count: int

	# Performance metrics
	avg_step_duration_ms: float
	total_duration_seconds: float
	idle_time_seconds: float

	# Cost metrics
	total_tokens: int
	total_cost_usd: float
	cost_per_step_usd: float

	# Browser metrics
	pages_visited: int
	unique_domains: int
	total_clicks: int
	total_form_fills: int
	screenshots_taken: int

	# Data metrics
	data_extracted_bytes: int
	files_generated: int
	errors_encountered: int
