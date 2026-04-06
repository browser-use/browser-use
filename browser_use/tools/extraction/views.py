"""Pydantic models for the extraction subsystem."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractionResult(BaseModel):
	"""Metadata about a structured extraction, stored in ActionResult.metadata."""

	model_config = ConfigDict(extra='forbid')

	data: dict[str, Any] = Field(description='The validated extraction payload')
	schema_used: dict[str, Any] = Field(description='The JSON Schema that was enforced')
	is_partial: bool = Field(default=False, description='True if content was truncated before extraction')
	source_url: str | None = Field(default=None, description='URL the content was extracted from')
	content_stats: dict[str, Any] = Field(default_factory=dict, description='Content processing statistics')
