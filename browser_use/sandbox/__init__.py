"""Sandbox execution package for browser-use

This package provides type-safe sandbox code execution with SSE streaming.

Example:
    from browser_use.sandbox import sandbox, SSEEvent, SSEEventType

    @sandbox(log_level="INFO")
    async def my_task(browser: Browser) -> str:
        page = await browser.get_current_page()
        await page.goto("https://example.com")
        return await page.title()

    result = await my_task()
"""

from browser_use.sandbox.sandbox import SandboxError, sandbox
from browser_use.sandbox.views import (
	BrowserCreatedData,
	ErrorData,
	ExecutionResponse,
	LogData,
	ResultData,
	SSEEvent,
	SSEEventType,
)

__all__ = [
	# Main decorator
	'sandbox',
	'SandboxError',
	# Event types
	'SSEEvent',
	'SSEEventType',
	# Event data models
	'BrowserCreatedData',
	'LogData',
	'ResultData',
	'ErrorData',
	'ExecutionResponse',
]
