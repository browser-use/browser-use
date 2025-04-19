from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str


class ClickElementAction(BaseModel):
	index: int
	xpath: Optional[str] = None


class InputTextAction(BaseModel):
	index: int
	text: str
	xpath: Optional[str] = None


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
	amount: Optional[int] = None  # The number of pixels to scroll. If None, scroll down/up one page


class SendKeysAction(BaseModel):
	keys: str


class GroupTabsAction(BaseModel):
	tab_ids: list[int] = Field(..., description='List of tab IDs to group')
	title: str = Field(..., description='Name for the tab group')
	color: Optional[str] = Field(
		'blue',
		description='Color for the group (grey/blue/red/yellow/green/pink/purple/cyan)',
	)


class UngroupTabsAction(BaseModel):
	tab_ids: list[int] = Field(..., description='List of tab IDs to ungroup')


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
	element_source: Optional[str] = Field(None, description='CSS selector or XPath of the element to drag from')
	element_target: Optional[str] = Field(None, description='CSS selector or XPath of the element to drop onto')
	element_source_offset: Optional[Position] = Field(
		None, description='Precise position within the source element to start drag (in pixels from top-left corner)'
	)
	element_target_offset: Optional[Position] = Field(
		None, description='Precise position within the target element to drop (in pixels from top-left corner)'
	)

	# Coordinate-based approach (used if selectors not provided)
	coord_source_x: Optional[int] = Field(None, description='Absolute X coordinate on page to start drag from (in pixels)')
	coord_source_y: Optional[int] = Field(None, description='Absolute Y coordinate on page to start drag from (in pixels)')
	coord_target_x: Optional[int] = Field(None, description='Absolute X coordinate on page to drop at (in pixels)')
	coord_target_y: Optional[int] = Field(None, description='Absolute Y coordinate on page to drop at (in pixels)')

	# Common options
	steps: Optional[int] = Field(10, description='Number of intermediate points for smoother movement (5-20 recommended)')
	delay_ms: Optional[int] = Field(5, description='Delay in milliseconds between steps (0 for fastest, 10-20 for more natural)')


# Memory Action Models
class MemorySaveAction(BaseModel):
	content: str = Field(
		..., description='The important information to store in memory for later retrieval - should be concise and valuable'
	)
	category: str = Field(
		'main', description='The category to organize this memory under (e.g., "product_info", "research", "user_preferences")'
	)


class MemoryRetrieveAction(BaseModel):
	query: str = Field(
		..., description='The search query to find relevant memories - be specific to get the most relevant results'
	)
	limit: int = Field(
		5, description='Maximum number of memory results to return - use a smaller number for more focused results'
	)
	category: str = Field(
		'main', description='The category to search within (e.g., "product_info", "research", "user_preferences")'
	)


class MemoryListAction(BaseModel):
	limit: int = Field(10, description='Maximum number of memories to return - increase if you need to see more stored memories')
	category: Optional[str] = Field(
		'', description='Optional filter to only list memories from a specific category (e.g., "research")'
	)


class MemoryDeleteAction(BaseModel):
	memory_id: str = Field(
		..., description='The ID of the memory to permanently delete - use memory_list or memory_retrieve first to find IDs'
	)
