"""Pydantic models for WebMCP tool descriptors and results"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebMCPToolDescriptor(BaseModel):
	"""Describes a single WebMCP tool registered by a web page via navigator.modelContext"""

	model_config = ConfigDict(extra='forbid')

	name: str = Field(description='Unique tool name as registered by the page.')
	description: str = Field(default='', description='Natural language description of what the tool does.')
	input_schema: dict[str, Any] = Field(default_factory=dict, description='JSON Schema for the tool input parameters.')


class WebMCPContentItem(BaseModel):
	"""A single content item in a WebMCP tool result"""

	model_config = ConfigDict(extra='forbid')

	type: str = Field(default='text', description='Content type (e.g. "text").')
	text: str = Field(default='', description='Text content.')


class WebMCPToolResult(BaseModel):
	"""Result returned from calling a WebMCP tool's execute callback"""

	model_config = ConfigDict(extra='allow')

	content: list[WebMCPContentItem] = Field(default_factory=list, description='Content items returned by the tool.')
	error: str | None = Field(default=None, description='Error message if the tool call failed.')
