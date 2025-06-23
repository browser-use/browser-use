from pydantic import BaseModel, ConfigDict, Field


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
	files_to_display: list[str] | None = []


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

	model_config = ConfigDict(extra='ignore')
	# No fields defined - all inputs are ignored automatically


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
