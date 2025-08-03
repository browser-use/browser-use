# @file purpose: Data models for tool exclusion service
"""
Data models and views for the tool exclusion service.
"""

from pydantic import BaseModel

from browser_use.agent.views import AgentStepInfo
from browser_use.browser.views import BrowserStateSummary
from browser_use.filesystem.file_system import FileSystem


class ExclusionContext(BaseModel):
	"""Context information for tool exclusion decisions"""

	model_config = {'arbitrary_types_allowed': True}

	# Required context
	browser_state: BrowserStateSummary

	# Optional context
	file_system: FileSystem | None = None
	available_file_paths: list[str] | None = None
	step_info: AgentStepInfo | None = None
	task: str | None = None
