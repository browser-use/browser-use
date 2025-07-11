from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str
	new_tab: bool = False  # True to open in new tab, False to navigate in current tab


class ClickElementAction(BaseModel):
	index: int


class InputTextAction(BaseModel):
	index: int
	text: str


class DoneAction(BaseModel):
	text: str
	success: bool
	files_to_display: list[str] | None = []


T = TypeVar('T', bound=BaseModel)


class StructuredOutputAction(BaseModel, Generic[T]):
	success: bool = True
	data: T


class SwitchTabAction(BaseModel):
	page_id: int


class CloseTabAction(BaseModel):
	page_id: int


class ScrollAction(BaseModel):
	down: bool  # True to scroll down, False to scroll up
	num_pages: float  # Number of pages to scroll (0.5 = half page, 1.0 = one page, etc.)
	index: int | None = None  # Optional element index to find scroll container for


class SendKeysAction(BaseModel):
	keys: str


class UploadFileAction(BaseModel):
	index: int
	path: str


class ExtractPageContentAction(BaseModel):
	value: str


class NoParamsAction(BaseModel):
	"""
	Accepts absolutely anything in the incoming data
	and discards it, so the final parsed model is empty.
	"""

	model_config = ConfigDict(extra='ignore')
	# No fields defined - all inputs are ignored automatically
