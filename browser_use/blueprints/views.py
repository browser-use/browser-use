"""
Pydantic models for Blueprint data structures.

These models match the Blueprint backend's API schema for communication.
"""

from typing import Any

from pydantic import BaseModel, Field


class BlueprintParameter(BaseModel):
	"""Parameter definition for a blueprint action."""

	name: str = Field(..., description='Parameter name')
	type: str = Field(..., description='Parameter type (string, number, boolean, object)')
	required: bool = Field(..., description='Whether parameter is required')
	description: str = Field(..., description='Parameter description for LLM')
	source: str = Field(..., description='Parameter source (user_input, browser_cookie, browser_headers, page_url)')


class BlueprintInputSchema(BaseModel):
	"""MCP-style input schema for blueprint."""

	type: str = Field(default='object', description='Schema type')
	properties: dict[str, Any] = Field(..., description='Property definitions')
	required: list[str] = Field(default_factory=list, description='Required property names')


class BlueprintMetadata(BaseModel):
	"""Metadata for a blueprint."""

	blueprint_id: str = Field(..., description='Unique blueprint identifier')
	blueprint_endpoint: str = Field(..., description='Full blueprint execution endpoint URL')
	domains: list[str] = Field(..., description='Applicable domains')
	requirements: dict[str, Any] | None = Field(None, description='Blueprint requirements (optional)')


class Blueprint(BaseModel):
	"""Blueprint definition from the backend."""

	name: str = Field(..., description='Human-readable name')
	description: str = Field(..., description='Description for LLM')
	inputSchema: BlueprintInputSchema = Field(..., description='Input schema')
	metadata: BlueprintMetadata = Field(..., description='Blueprint metadata')


class BlueprintListResponse(BaseModel):
	"""Response from GET /list endpoint."""

	tools: list[Blueprint] = Field(default_factory=list, description='Available blueprints')


class BlueprintErrorInfo(BaseModel):
	"""Error information from blueprint execution."""

	code: str = Field(..., description='Error code')
	message: str = Field(..., description='Error message')
	missing_parameters: list[str] | None = Field(None, description='Missing parameters if applicable')


class BlueprintExecutionResponse(BaseModel):
	"""Response from blueprint execution."""

	success: bool = Field(..., description='Whether execution succeeded')
	data: Any | None = Field(None, description='Execution result data')
	error: BlueprintErrorInfo | None = Field(None, description='Error information if failed')


class BlueprintExecutionRequest(BaseModel):
	"""Request for blueprint execution."""

	blueprint_id: str = Field(..., description='Blueprint ID to execute')
	parameters: dict[str, Any] = Field(default_factory=dict, description='Execution parameters')
	metadata: dict[str, Any] | None = Field(None, description='Optional request metadata')
