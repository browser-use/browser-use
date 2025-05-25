from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

# --- Define a shared Literal for all granular fact types ---
GranularFactType = Literal[
	'user_preference',
	'page_content_summary',
	'key_finding',
	'action_taken',
	'action_outcome_success',
	'action_outcome_failure',
	'navigation_milestone',
	'agent_reflection',
	'user_instruction',
	'raw_text',
]


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str


class ClickElementAction(BaseModel):
	index: int
	xpath: str | None = None


class InputTextAction(BaseModel):
	index: int
	text: str
	xpath: str | None = None


class DoneAction(BaseModel):
	text: str
	success: bool


class SwitchTabAction(BaseModel):
	page_id: int


class OpenTabAction(BaseModel):
	url: str


class CloseTabAction(BaseModel):
	page_id: int


class ScrollAction(BaseModel):
	amount: int | None = None  # The number of pixels to scroll. If None, scroll down/up one page


class SendKeysAction(BaseModel):
	keys: str


class ExtractPageContentAction(BaseModel):
	value: str


class NoParamsAction(BaseModel):
	"""
	Accepts absolutely anything in the incoming data
	and discards it, so the final parsed model is empty.
	"""

	model_config = ConfigDict(extra='allow')

	@model_validator(mode='before')
	def ignore_all_inputs(cls, values):
		# No matter what the user sends, discard it and return empty.
		return {}


class Position(BaseModel):
	x: int
	y: int


class DragDropAction(BaseModel):
	# Element-based approach
	element_source: str | None = Field(None, description='CSS selector or XPath of the element to drag from')
	element_target: str | None = Field(None, description='CSS selector or XPath of the element to drop onto')
	element_source_offset: Position | None = Field(
		None, description='Precise position within the source element to start drag (in pixels from top-left corner)'
	)
	element_target_offset: Position | None = Field(
		None, description='Precise position within the target element to drop (in pixels from top-left corner)'
	)

	# Coordinate-based approach (used if selectors not provided)
	coord_source_x: int | None = Field(None, description='Absolute X coordinate on page to start drag from (in pixels)')
	coord_source_y: int | None = Field(None, description='Absolute Y coordinate on page to start drag from (in pixels)')
	coord_target_x: int | None = Field(None, description='Absolute X coordinate on page to drop at (in pixels)')
	coord_target_y: int | None = Field(None, description='Absolute Y coordinate on page to drop at (in pixels)')

	# Common options
	steps: int | None = Field(10, description='Number of intermediate points for smoother movement (5-20 recommended)')
	delay_ms: int | None = Field(5, description='Delay in milliseconds between steps (0 for fastest, 10-20 for more natural)')


# --- Pydantic models for Memory Actions ---
class SaveFactToMemoryAction(BaseModel):
	fact_content: str = Field(description='The textual content of the fact to be saved.')
	fact_type: GranularFactType = Field(description='The type or category of the fact.')
	source_url: str | None = Field(default=None, description='Optional URL where the information was found.')
	keywords: list[str] | None = Field(default_factory=list, description='Optional keywords for easier filtering.')
	confidence: float | None = Field(default=None, description="Optional agent's confidence in this fact (0.0 to 1.0).")


class QueryLongTermMemoryAction(BaseModel):
	query_text: str = Field(description='The natural language query to search the memory.')
	fact_types: list[GranularFactType] | None = Field(default=None, description='Optional list of fact types to filter by.')
	relevant_to_url: str | None = Field(default=None, description='Optional URL to find facts relevant to.')
	max_results: int = Field(default=3, gt=0, le=10, description='Maximum number of results to return.')
