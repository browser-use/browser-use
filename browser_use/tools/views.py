from typing import Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


# Action Input Models
class ExtractAction(BaseModel):
	query: str
	extract_links: bool = Field(
		default=False, description='Set True to true if the query requires links, else false to safe tokens'
	)
	extract_images: bool = Field(
		default=False,
		description='Set True to include image src URLs in extracted markdown. Auto-enabled when query contains image-related keywords.',
	)
	start_from_char: int = Field(
		default=0, description='Use this for long markdowns to start from a specific character (not index in browser_state)'
	)
	output_schema: SkipJsonSchema[dict | None] = Field(
		default=None,
		description='Optional JSON Schema dict. When provided, extraction returns validated JSON matching this schema instead of free-text.',
	)
	already_collected: list[str] = Field(
		default_factory=list,
		description='Item identifiers (name, URL, or ID) already collected in prior extract calls on other pages. The extractor will skip items matching these to prevent duplicates. Use when paginating across multiple pages.',
	)


class SearchPageAction(BaseModel):
	# Accept `query` as an alias for `pattern` — models frequently emit search_page.query.
	model_config = ConfigDict(populate_by_name=True)

	pattern: str = Field(
		validation_alias=AliasChoices('pattern', 'query', 'text'),
		description='Text or regex pattern to search for in page content',
	)
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
	text: str = Field(description='Text to enter. With clear=True, text="" clears the field without typing.')
	clear: bool = Field(default=True, description='Clear existing text before typing. Set to False to append instead.')


class DoneAction(BaseModel):
	text: str = Field(
		description=(
			'Final message to the user. '
			'ONLY report data you directly observed in browser_state, tool outputs, or screenshots during this session. '
			'Do NOT use training knowledge to fill gaps — if information was not found on the page, say so explicitly. '
			'Do NOT claim completion of steps from compacted_memory or prior session summaries '
			'unless you explicitly verified them yourself. '
			'If uncertain whether a prior step completed, say so explicitly. '
			'When success=true, include the concrete verification evidence you observed, such as a URL, page text, '
			'confirmation message, extracted table/list values, or file content. For forms, purchases, ticketing, maps, '
			'prices, rankings, and calculations, do not mark success=true unless the final page state or extracted '
			'content confirms the requested result.'
		)
	)
	success: bool = Field(
		default=True,
		description=(
			'True only if the user_request was completed and verified from evidence observed in this browser session. '
			'Use false when blocked, unsure, missing required data, or unable to verify submission/result.'
		),
	)
	files_to_display: list[str] | None = Field(default=[])


T = TypeVar('T', bound=BaseModel)


def _hide_internal_fields_from_schema(schema: dict) -> None:
	"""Remove internal fields from the JSON schema to avoid collisions with user models."""
	props = schema.get('properties', {})
	props.pop('success', None)
	props.pop('files_to_display', None)


class StructuredOutputAction(BaseModel, Generic[T]):
	model_config = ConfigDict(json_schema_extra=_hide_internal_fields_from_schema)

	success: bool = Field(
		default=True,
		description=(
			'True only if the user_request was completed and verified from evidence observed in this browser session. '
			'Use false when blocked, unsure, missing required data, or unable to verify submission/result.'
		),
	)
	data: T = Field(
		description=(
			'The actual output data matching the requested schema. Populate it only with values observed from '
			'browser_state, tool outputs, screenshots, or files in this session; do not infer missing fields.'
		)
	)
	files_to_display: list[str] | None = Field(default=[])


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


class SaveAsPdfAction(BaseModel):
	file_name: str | None = Field(
		default=None,
		description='Output PDF filename (without path). Defaults to page title. Extension .pdf is added automatically if missing.',
	)
	print_background: bool = Field(default=True, description='Include background graphics and colors')
	landscape: bool = Field(default=False, description='Use landscape orientation')
	scale: float = Field(default=1.0, ge=0.1, le=2.0, description='Scale of the webpage rendering (0.1 to 2.0)')
	paper_format: str = Field(
		default='Letter',
		description='Paper size: Letter, Legal, A4, A3, or Tabloid',
	)


class GetDropdownOptionsAction(BaseModel):
	index: int


class SelectDropdownOptionAction(BaseModel):
	index: int
	text: str = Field(description='exact text/value')


class UseAccountAction(BaseModel):
	"""Action to load and activate a specific user account for the current page."""

	model_config = ConfigDict(extra='ignore')

	label: str = Field(description='Account label or platform name (e.g. "my github", "淘宝账号", "taobao")')


class AutoFillLoginAction(BaseModel):
	"""Automatically fill visible login fields with a matching stored account."""

	model_config = ConfigDict(extra='ignore')

	label: str | None = Field(
		default=None,
		description='Optional account label or platform name. If omitted, the current page URL is used to find a matching account.',
	)
	submit: bool = Field(
		default=False,
		description='Click a detected login/submit button after filling. Defaults to false so the agent can inspect the result first.',
	)


class GitHubNavigateAction(BaseModel):
	"""Action to navigate within a GitHub repository."""

	action_type: str = Field(
		description='Navigation type: "search_code", "go_to_file", "go_to_function", "browse_tree", "view_issues", "view_prs", "view_commits"'
	)
	query: str | None = Field(default=None, description='Search query for code/function search')
	path: str | None = Field(default=None, description='File or directory path within the repo')
	repo: str | None = Field(default=None, description='Repository in owner/name format. Auto-detected from current URL if not provided.')
	branch: str | None = Field(default=None, description='Branch name. Defaults to main/master.')


class WaitForUserInputAction(BaseModel):
	"""Pause and wait for the user to manually input something (e.g. SMS verification code) in the browser."""

	model_config = ConfigDict(extra='ignore')

	message: str = Field(description='Message to display to the user explaining what input is needed (e.g. "Please enter the SMS verification code sent to 185****6106")')
	timeout_seconds: int = Field(default=120, description='How long to wait for user input before timing out (default 120s)')


class EvaluateJsAction(BaseModel):
	"""Execute JavaScript in the page. Accepts `code` (canonical) or `script`/`js`/`expression` aliases."""

	model_config = ConfigDict(populate_by_name=True)

	code: str = Field(
		validation_alias=AliasChoices('code', 'script', 'js', 'javascript', 'expression'),
		description='JavaScript code to execute in the browser page context.',
	)


class WriteFileAction(BaseModel):
	"""Write/overwrite a file. Accepts `content` (canonical) or `text`/`data` aliases."""

	model_config = ConfigDict(populate_by_name=True)

	file_name: str = Field(validation_alias=AliasChoices('file_name', 'filename', 'path', 'name'), description='File name to write')
	content: str = Field(validation_alias=AliasChoices('content', 'text', 'data'), description='Full file content to write')
	append: bool = Field(default=False, description='Append instead of overwrite')
	trailing_newline: bool = Field(default=True, description='Add trailing newline')
	leading_newline: bool = Field(default=False, description='Add leading newline')


class ReplaceFileAction(BaseModel):
	"""Replace a substring within a file. Use old_str/new_str for targeted edits (NOT whole-file replacement)."""

	model_config = ConfigDict(populate_by_name=True)

	file_name: str = Field(validation_alias=AliasChoices('file_name', 'filename', 'path', 'name'), description='File name to edit')
	old_str: str = Field(
		validation_alias=AliasChoices('old_str', 'old_string', 'old', 'find', 'search'),
		description='Exact existing text to find and replace',
	)
	new_str: str = Field(
		validation_alias=AliasChoices('new_str', 'new_string', 'new', 'replace', 'replacement'),
		description='Replacement text',
	)
