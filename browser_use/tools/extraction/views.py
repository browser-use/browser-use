"""Data models for the extraction subsystem."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class ExtractionResult(BaseModel):
	"""Result of a structured extraction operation."""

	model_config = ConfigDict(extra='forbid')

	data: Any = Field(description='Extracted data (validated JSON when schema provided, free text otherwise)')
	schema_used: bool = Field(default=False, description='Whether a schema was used for validation')
	is_partial: bool = Field(default=False, description='Whether extraction was truncated/incomplete')
	source_url: str | None = Field(default=None, description='URL the data was extracted from')
	content_stats: dict[str, Any] | None = Field(default=None, description='Content processing statistics')


class ExtractionError(BaseModel):
	"""Details about an extraction failure."""

	model_config = ConfigDict(extra='forbid')

	error_type: str = Field(description='Category: schema_validation, js_execution, timeout, llm_error')
	message: str = Field(description='Human-readable error description')
	retries_exhausted: bool = Field(default=False)
	fallback_used: bool = Field(default=False, description='Whether fallback to free-text was used')


class ExtractionRetryConfig(BaseModel):
	"""Configuration for extraction retry behavior."""

	model_config = ConfigDict(extra='forbid')

	max_retries: int = Field(default=1, ge=0, le=3)
	retry_on_validation_error: bool = Field(default=True)
	retry_on_js_error: bool = Field(default=True)
	fallback_to_freetext: bool = Field(default=True, description='Fall back to free-text extraction on failure')


class ExtractionStrategy(BaseModel):
	"""A cached extraction strategy for reuse across similar pages."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	url_pattern: str = Field(description='URL glob pattern, e.g. "https://example.com/products/*"')
	js_script: str | None = Field(default=None, description='Cached JS extraction script')
	css_selector: str | None = Field(default=None, description='CSS selector to narrow extraction scope')
	output_schema: dict[str, Any] | None = Field(default=None, description='Expected output schema')
	query_template: str = Field(description='Original extraction query')
	success_count: int = Field(default=0, ge=0)
	failure_count: int = Field(default=0, ge=0)
