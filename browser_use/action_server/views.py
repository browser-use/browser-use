"""
Pydantic models for Browser Action Server API.

Defines request/response schemas for all browser action endpoints.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class BaseRequest(BaseModel):
	"""Base class for all action requests"""
	
	model_config = ConfigDict(extra='forbid', validate_by_name=True)
	
	timeout: float = Field(default=10.0, ge=0.1, le=300.0, description="Timeout in seconds")
	wait_for_load: bool = Field(default=True, description="Wait for page load after action")


class NavigateRequest(BaseRequest):
	"""Request to navigate to a URL"""
	
	url: str = Field(description="URL to navigate to", min_length=1)
	wait_until: Literal['load', 'domcontentloaded', 'networkidle'] = Field(
		default='domcontentloaded',
		description="When to consider navigation complete"
	)


class ClickRequest(BaseRequest):
	"""Request to click an element"""
	
	selector: str = Field(description="CSS selector for element to click", min_length=1)
	button: Literal['left', 'right', 'middle'] = Field(default='left', description="Mouse button to click")
	click_count: int = Field(default=1, ge=1, le=3, description="Number of clicks (1=single, 2=double)")
	position: tuple[float, float] | None = Field(default=None, description="Specific position to click (x, y)")


class TypeRequest(BaseRequest):
	"""Request to type text into an element"""
	
	selector: str = Field(description="CSS selector for element to type into", min_length=1)
	text: str = Field(description="Text to type", min_length=0)
	clear_first: bool = Field(default=True, description="Clear existing text before typing")
	delay: float = Field(default=0.0, ge=0.0, le=1.0, description="Delay between keystrokes (seconds)")


class ScrollRequest(BaseRequest):
	"""Request to scroll the page or an element"""
	
	direction: Literal['up', 'down', 'left', 'right'] = Field(description="Scroll direction")
	amount: int = Field(default=300, ge=1, description="Pixels to scroll")
	selector: str | None = Field(default=None, description="CSS selector of element to scroll (if not page)")
	smooth: bool = Field(default=True, description="Use smooth scrolling")


class HoverRequest(BaseRequest):
	"""Request to hover over an element"""
	
	selector: str = Field(description="CSS selector for element to hover", min_length=1)
	position: tuple[float, float] | None = Field(default=None, description="Specific position to hover (x, y)")


class WaitRequest(BaseRequest):
	"""Request to wait for an element or condition"""
	
	condition_type: Literal['element', 'text', 'url', 'timeout'] = Field(description="What to wait for")
	selector: str | None = Field(default=None, description="CSS selector (for element/text conditions)")
	text: str | None = Field(default=None, description="Text to wait for")
	url: str | None = Field(default=None, description="URL pattern to wait for")
	visible: bool = Field(default=True, description="Element should be visible (for element condition)")


class SelectRequest(BaseRequest):
	"""Request to select option in dropdown"""
	
	selector: str = Field(description="CSS selector for select element", min_length=1)
	value: str | None = Field(default=None, description="Option value to select")
	label: str | None = Field(default=None, description="Option label to select")
	index: int | None = Field(default=None, description="Option index to select")


class UploadRequest(BaseRequest):
	"""Request to upload file to input element"""
	
	selector: str = Field(description="CSS selector for file input", min_length=1)
	file_path: str = Field(description="Path to file to upload", min_length=1)


# Response Models

class BaseResponse(BaseModel):
	"""Base class for all responses"""
	
	model_config = ConfigDict(extra='forbid', validate_by_name=True, frozen=False)
	
	success: bool = Field(description="Whether the action succeeded")
	timestamp: str = Field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%SZ'), description="Response timestamp")
	execution_time_ms: float = Field(default=0.0, description="Time taken to execute action in milliseconds")
	request_id: str = Field(default_factory=uuid7str, description="Unique request identifier")


class ActionResponse(BaseResponse):
	"""Response for successful actions"""
	
	success: Literal[True] = True
	data: dict[str, Any] = Field(description="Action-specific response data")
	message: str = Field(default="Action completed successfully", description="Human-readable success message")


class ErrorDetail(BaseModel):
	"""Detailed error information"""
	
	model_config = ConfigDict(extra='forbid', validate_by_name=True)
	
	type: str = Field(description="Error type/category")
	message: str = Field(description="Error message")
	details: dict[str, Any] = Field(default_factory=dict, description="Additional error details")
	recoverable: bool = Field(default=True, description="Whether the error might be recoverable")


class ErrorResponse(BaseResponse):
	"""Response for failed actions"""
	
	success: Literal[False] = False
	error: ErrorDetail = Field(description="Error details")
	data: None = None


class PageStatusResponse(BaseResponse):
	"""Response with current page status information"""
	
	success: Literal[True] = True
	data: dict[str, Any] = Field(description="Page status data")
	
	@classmethod
	def create(
		cls,
		url: str,
		title: str,
		loading: bool = False,
		ready_state: str = 'complete',
		viewport_size: tuple[int, int] | None = None,
		scroll_position: tuple[int, int] | None = None,
		element_count: int = 0,
		execution_time_ms: float = 0.0
	) -> PageStatusResponse:
		"""Create page status response with common fields"""
		data = {
			'url': url,
			'title': title,
			'loading': loading,
			'ready_state': ready_state,
			'element_count': element_count
		}
		
		if viewport_size:
			data['viewport_size'] = {'width': viewport_size[0], 'height': viewport_size[1]}
			
		if scroll_position:
			data['scroll_position'] = {'x': scroll_position[0], 'y': scroll_position[1]}
		
		return cls(
			data=data,
			execution_time_ms=execution_time_ms
		)


class ScreenshotResponse(BaseResponse):
	"""Response with screenshot data"""
	
	success: Literal[True] = True
	data: dict[str, Any] = Field(description="Screenshot data")
	
	@classmethod
	def create(
		cls,
		screenshot_base64: str,
		format: str = 'png',
		size: tuple[int, int] | None = None,
		execution_time_ms: float = 0.0
	) -> ScreenshotResponse:
		"""Create screenshot response"""
		data = {
			'screenshot': screenshot_base64,
			'format': format,
			'size_bytes': len(screenshot_base64) if screenshot_base64 else 0
		}
		
		if size:
			data['dimensions'] = {'width': size[0], 'height': size[1]}
		
		return cls(
			data=data,
			execution_time_ms=execution_time_ms
		)


class ElementInfoResponse(BaseResponse):
	"""Response with element information"""
	
	success: Literal[True] = True
	data: dict[str, Any] = Field(description="Element information")
	
	@classmethod
	def create(
		cls,
		selector: str,
		found: bool,
		element_info: dict[str, Any] | None = None,
		execution_time_ms: float = 0.0
	) -> ElementInfoResponse:
		"""Create element info response"""
		data = {
			'selector': selector,
			'found': found,
			'element': element_info if found else None
		}
		
		return cls(
			data=data,
			execution_time_ms=execution_time_ms
		)


class HealthResponse(BaseResponse):
	"""Response for health check"""
	
	success: Literal[True] = True
	data: dict[str, Any] = Field(description="Health status data")
	
	@classmethod
	def create(
		cls,
		status: str = 'healthy',
		version: str = '1.0.0',
		browser_connected: bool = False,
		uptime_seconds: float = 0.0,
		total_requests: int = 0,
		execution_time_ms: float = 0.0
	) -> HealthResponse:
		"""Create health check response"""
		data = {
			'status': status,
			'version': version,
			'server': 'browser-action-server',
			'browser_connected': browser_connected,
			'uptime_seconds': uptime_seconds,
			'total_requests': total_requests
		}
		
		return cls(
			data=data,
			execution_time_ms=execution_time_ms
		)


# Union types for response handling
ActionResponseType = ActionResponse | ErrorResponse
AnyResponse = ActionResponse | ErrorResponse | PageStatusResponse | ScreenshotResponse | ElementInfoResponse | HealthResponse