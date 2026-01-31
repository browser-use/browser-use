import json
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_output_schema(v: Any) -> dict[str, Any] | None:
	"""Accept both dict and JSON string for output_schema.

	Google Gemini cannot represent free-form objects in its response schema,
	so the schema fixer converts dict fields to STRING type. This validator
	ensures the field works regardless of whether the LLM returns a dict or
	a JSON string.
	"""
	if v is None:
		return None
	if isinstance(v, dict):
		return v
	if isinstance(v, str):
		try:
			parsed = json.loads(v)
			if isinstance(parsed, dict):
				return parsed
		except (json.JSONDecodeError, TypeError):
			pass
		return None
	return v if isinstance(v, dict) else None


_OutputSchema = Annotated[dict[str, Any] | None, BeforeValidator(_coerce_output_schema)]


# Action Input Models
class ExtractAction(BaseModel):
	query: str
	extract_links: bool = Field(
		default=False, description='Set True to true if the query requires links, else false to safe tokens'
	)
	start_from_char: int = Field(
		default=0, description='Use this for long markdowns to start from a specific character (not index in browser_state)'
	)
	output_schema: _OutputSchema = Field(
		default=None,
		description='Optional JSON Schema dict. When provided, extraction returns validated JSON matching this schema instead of free text.',
	)


class ExtractWithScriptAction(BaseModel):
	query: str
	output_schema: _OutputSchema = Field(
		default=None,
		description='Optional JSON Schema dict for structured output validation',
	)
	css_selector: str | None = Field(
		default=None,
		description='CSS selector to narrow extraction to a specific page region',
	)
	extraction_id: str | None = Field(
		default=None,
		description='Reuse a previously generated script on a similar page',
	)


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


class StructuredOutputAction(BaseModel, Generic[T]):
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


class GetDropdownOptionsAction(BaseModel):
	index: int


class SelectDropdownOptionAction(BaseModel):
	index: int
	text: str = Field(description='exact text/value')
