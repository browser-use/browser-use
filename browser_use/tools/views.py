from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


# Action Input Models
class ExtractAction(BaseModel):
	query: str
	extract_links: bool = Field(
		default=False, description='Set True to true if the query requires links, else false to safe tokens'
	)
	start_from_char: int = Field(
		default=0, description='Use this for long markdowns to start from a specific character (not index in browser_state)'
	)
	output_schema: SkipJsonSchema[dict | None] = Field(
		default=None,
		description='Optional JSON Schema dict. When provided, extraction returns validated JSON matching this schema instead of free-text.',
	)


class SearchPageAction(BaseModel):
	pattern: str = Field(description='Text or regex pattern to search for in page content')
	regex: bool = Field(default=False, description='Treat pattern as regex (default: literal text match)')
	case_sensitive: bool = Field(default=False, description='Case-sensitive search (default: case-insensitive)')
	context_chars: int = Field(default=150, description='Characters of surrounding context per match')
	css_scope: str | None = Field(default=None, description='CSS selector to limit search scope (e.g. "div#main")')
	max_results: int = Field(default=25, description='Maximum matches to return')


class FindElementsAction(BaseModel):
	selector: str = Field(description='CSS selector to query elements (e.g. "table tr", "a.link", "div.product")')
	attributes: list[str] | None = Field(
		default=None,
		description='Specific attributes to extract (e.g. ["href", "src", "class"]). If not set, returns tag and text only.',
	)
	max_results: int = Field(default=50, description='Maximum elements to return')
	include_text: bool = Field(default=True, description='Include text content of each element')


class SearchAction(BaseModel):
	query: str
	engine: str = Field(
		default='duckduckgo', description='duckduckgo, google, bing (use duckduckgo by default because less captchas)'
	)


# Backward compatibility alias
SearchAction = SearchAction


class NavigateAction(BaseModel):
	url: str
	new_tab: bool = Field(default=False)


# Backward compatibility alias
GoToUrlAction = NavigateAction


class ClickElementAction(BaseModel):
	index: int | None = Field(default=None, ge=1, description='Element index from browser_state')
	coordinate_x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')
	# expect_download: bool = Field(default=False, description='set True if expecting a download, False otherwise')  # moved to downloads_watchdog.py
	# click_count: int = 1  # TODO


class ClickElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='ClickElementAction')

	index: int = Field(ge=1, description='Element index from browser_state')


class InputTextAction(BaseModel):
	index: int = Field(ge=0, description='from browser_state')
	text: str
	clear: bool = Field(default=True, description='1=clear, 0=append')


class DoneAction(BaseModel):
	text: str = Field(description='Final user message in the format the user requested')
	success: bool = Field(default=True, description='True if user_request completed successfully')
	files_to_display: list[str] | None = Field(default=[])


T = TypeVar('T', bound=BaseModel)


def _hide_success_from_schema(schema: dict) -> None:
	"""Remove 'success' from the JSON schema to avoid field name collisions with user models."""
	schema.get('properties', {}).pop('success', None)


class StructuredOutputAction(BaseModel, Generic[T]):
	model_config = ConfigDict(json_schema_extra=_hide_success_from_schema)

	success: bool = Field(default=True, description='True if user_request completed successfully')
	data: T = Field(description='The actual output data matching the requested schema')


class SwitchTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')


class CloseTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')


class ScrollAction(BaseModel):
	down: bool = Field(default=True, description='down=True=scroll down, down=False scroll up')
	pages: float = Field(default=1.0, description='0.5=half page, 1=full page, 10=to bottom/top')
	index: int | None = Field(default=None, description='Optional element index to scroll within specific element')


class SendKeysAction(BaseModel):
	keys: str = Field(description='keys (Escape, Enter, PageDown) or shortcuts (Control+o)')


class UploadFileAction(BaseModel):
	index: int
	path: str


class NoParamsAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	# Optional field required by Gemini API which errors on empty objects in response_schema
	description: str | None = Field(None, description='Optional description for the action')


class ScreenshotAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	file_name: str | None = Field(
		default=None,
		description='If provided, saves screenshot to this file and returns path. Otherwise screenshot is included in next observation.',
	)


class ReadContentAction(BaseModel):
	"""Action for intelligent reading of long content."""

	goal: str = Field(description='What to look for or extract from the content')
	source: str = Field(
		default='page',
		description='What to read: "page" for current webpage, or a file path',
	)
	context: str = Field(default='', description='Additional context about the task')


class GetDropdownOptionsAction(BaseModel):
	index: int


class SelectDropdownOptionAction(BaseModel):
	index: int
	text: str = Field(description='exact text/value')
