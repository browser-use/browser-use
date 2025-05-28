from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator, validator


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str


class ClickElementAction(BaseModel):
	index: int
	xpath: str | None = None


class DateNavigationMode(str, Enum):
	DATE = 'date'
	MONTH = 'month'
	YEAR = 'year'
	MONTH_YEAR = 'month-year'


class DateTarget(BaseModel):
	"""Target date components for navigation"""

	date: int | None = Field(None, ge=1, le=31, description='Day of month (1-31)')
	month: str | None = Field(None, description="Full month name (e.g., 'January', 'February')")
	year: int | float | None = Field(None, description='Full year (e.g., 2024)')

	class Config:
		extra = 'ignore'  # Ignore extra fields
		arbitrary_types_allowed = True

	@validator('month', pre=True)
	def validate_month(cls, v):
		if v is None:
			return None

		if not isinstance(v, str):
			v = str(v)

		v = v.strip().title()
		try:
			datetime.strptime(v, '%B')
			return v
		except ValueError:
			raise ValueError("Month must be a full month name (e.g., 'January', 'February')")

	@validator('year', pre=True)
	def validate_year(cls, v):
		if v is None:
			return None

		try:
			return int(float(v))
		except (ValueError, TypeError):
			raise ValueError('Year must be a valid number')


class ClickElementMultipleTimesAction(BaseModel):
	"""
	Action model for clicking an element multiple times based on date navigation.

	Args:
	    index: The index of the element to click
	    mode: The type of date navigation ('date', 'month', 'year', 'month-year')
	    current: Current date components
	    target: Target date components to navigate to
	"""

	index: int
	mode: DateNavigationMode
	current: DateTarget
	target: DateTarget
	xpath: str | None = Field(None, description='XPath of the element to click (alternative to index)')

	@validator('index')
	def validate_index(cls, v):
		if v is None:
			raise ValueError('Index is required')
		return int(v)  # Convert float to int if needed


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
