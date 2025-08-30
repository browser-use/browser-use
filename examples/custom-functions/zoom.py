"""
Example of implementing zoom in/out functionality with custom functions.

This shows how to control browser zoom level using CDP (Chrome DevTools Protocol)
by manipulating the device scale factor, which effectively zooms the page content.

The zoom functionality implemented here:
- Zoom in: Increase device scale factor to make content appear larger
- Zoom out: Decrease device scale factor to make content appear smaller  
- Get current zoom: Retrieve the current zoom level
- Reset zoom: Set zoom back to 100% (scale factor 1.0)

@file purpose: Demonstrates zoom control via CDP device scale factor manipulation
"""

import asyncio
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import ActionResult, Agent, ChatOpenAI, Controller
from browser_use.browser.session import BrowserSession

logger = logging.getLogger(__name__)

# Initialize controller
controller = Controller()

# Store current zoom level (device scale factor)
current_zoom_level = 1.0


@controller.registry.action('Zoom in to make page content larger')
async def zoom_in(browser_session: BrowserSession, zoom_factor: float = 0.2) -> ActionResult:
	"""
	Zoom in by increasing the device scale factor.
	
	Args:
		browser_session: The current browser session
		zoom_factor: Amount to zoom in (default 0.2 = 20% increase)
	
	Returns:
		ActionResult with success/error message
	"""
	global current_zoom_level
	
	try:
		# Calculate new zoom level
		new_zoom_level = current_zoom_level + zoom_factor
		
		# Limit maximum zoom to 5.0 (500%) to prevent issues
		if new_zoom_level > 5.0:
			return ActionResult(
				extracted_content=f'Cannot zoom in further. Maximum zoom level is 500%. Current: {current_zoom_level * 100:.0f}%',
				include_in_memory=True
			)
		
		# Get current page info to maintain viewport dimensions
		page_info = await browser_session.get_page_info()
		
		# Apply zoom by setting device scale factor
		await browser_session._cdp_set_viewport(
			width=page_info.viewport_width,
			height=page_info.viewport_height,
			device_scale_factor=new_zoom_level,
			mobile=False
		)
		
		current_zoom_level = new_zoom_level
		
		return ActionResult(
			extracted_content=f'Zoomed in successfully. New zoom level: {current_zoom_level * 100:.0f}%',
			include_in_memory=True
		)
		
	except Exception as e:
		logger.error(f'Failed to zoom in: {e}')
		return ActionResult(
			error=f'Failed to zoom in: {str(e)}',
			include_in_memory=True
		)


@controller.registry.action('Zoom out to make page content smaller')
async def zoom_out(browser_session: BrowserSession, zoom_factor: float = 0.2) -> ActionResult:
	"""
	Zoom out by decreasing the device scale factor.
	
	Args:
		browser_session: The current browser session
		zoom_factor: Amount to zoom out (default 0.2 = 20% decrease)
	
	Returns:
		ActionResult with success/error message
	"""
	global current_zoom_level
	
	try:
		# Calculate new zoom level
		new_zoom_level = current_zoom_level - zoom_factor
		
		# Limit minimum zoom to 0.25 (25%) to prevent issues
		if new_zoom_level < 0.25:
			return ActionResult(
				extracted_content=f'Cannot zoom out further. Minimum zoom level is 25%. Current: {current_zoom_level * 100:.0f}%',
				include_in_memory=True
			)
		
		# Get current page info to maintain viewport dimensions
		page_info = await browser_session.get_page_info()
		
		# Apply zoom by setting device scale factor
		await browser_session._cdp_set_viewport(
			width=page_info.viewport_width,
			height=page_info.viewport_height,
			device_scale_factor=new_zoom_level,
			mobile=False
		)
		
		current_zoom_level = new_zoom_level
		
		return ActionResult(
			extracted_content=f'Zoomed out successfully. New zoom level: {current_zoom_level * 100:.0f}%',
			include_in_memory=True
		)
		
	except Exception as e:
		logger.error(f'Failed to zoom out: {e}')
		return ActionResult(
			error=f'Failed to zoom out: {str(e)}',
			include_in_memory=True
		)


@controller.registry.action('Get current zoom level')
async def get_zoom_level() -> ActionResult:
	"""
	Get the current zoom level as a percentage.
	
	Returns:
		ActionResult with current zoom level information
	"""
	global current_zoom_level
	
	zoom_percentage = current_zoom_level * 100
	
	return ActionResult(
		extracted_content=f'Current zoom level: {zoom_percentage:.0f}% (device scale factor: {current_zoom_level})',
		include_in_memory=True
	)


@controller.registry.action('Reset zoom to default 100%')
async def reset_zoom(browser_session: BrowserSession) -> ActionResult:
	"""
	Reset zoom level back to 100% (device scale factor 1.0).
	
	Args:
		browser_session: The current browser session
	
	Returns:
		ActionResult with success/error message
	"""
	global current_zoom_level
	
	try:
		# Get current page info to maintain viewport dimensions
		page_info = await browser_session.get_page_info()
		
		# Reset zoom to 100% (scale factor 1.0)
		await browser_session._cdp_set_viewport(
			width=page_info.viewport_width,
			height=page_info.viewport_height,
			device_scale_factor=1.0,
			mobile=False
		)
		
		current_zoom_level = 1.0
		
		return ActionResult(
			extracted_content='Zoom reset to 100% successfully',
			include_in_memory=True
		)
		
	except Exception as e:
		logger.error(f'Failed to reset zoom: {e}')
		return ActionResult(
			error=f'Failed to reset zoom: {str(e)}',
			include_in_memory=True
		)


@controller.registry.action('Set specific zoom level')
async def set_zoom_level(browser_session: BrowserSession, zoom_percentage: int) -> ActionResult:
	"""
	Set a specific zoom level as a percentage.
	
	Args:
		browser_session: The current browser session
		zoom_percentage: Target zoom level as percentage (e.g., 150 for 150%)
	
	Returns:
		ActionResult with success/error message
	"""
	global current_zoom_level
	
	try:
		# Convert percentage to scale factor
		scale_factor = zoom_percentage / 100.0
		
		# Validate zoom range (25% to 500%)
		if scale_factor < 0.25 or scale_factor > 5.0:
			return ActionResult(
				error=f'Zoom level must be between 25% and 500%. Requested: {zoom_percentage}%',
				include_in_memory=True
			)
		
		# Get current page info to maintain viewport dimensions
		page_info = await browser_session.get_page_info()
		
		# Set zoom level
		await browser_session._cdp_set_viewport(
			width=page_info.viewport_width,
			height=page_info.viewport_height,
			device_scale_factor=scale_factor,
			mobile=False
		)
		
		current_zoom_level = scale_factor
		
		return ActionResult(
			extracted_content=f'Zoom level set to {zoom_percentage}% successfully',
			include_in_memory=True
		)
		
	except Exception as e:
		logger.error(f'Failed to set zoom level: {e}')
		return ActionResult(
			error=f'Failed to set zoom level: {str(e)}',
			include_in_memory=True
		)


async def main():
	"""
	Example task demonstrating zoom functionality.
	
	This will:
	1. Navigate to a webpage
	2. Check current zoom level
	3. Zoom in a few times
	4. Zoom out to see more content
	5. Reset zoom to default
	6. Set a specific zoom level
	"""
	task = """
	Navigate to https://example.com and then:
	1. Check the current zoom level
	2. Zoom in twice to make the text larger
	3. Check zoom level again
	4. Zoom out once to reduce the zoom
	5. Reset zoom back to 100%
	6. Set zoom to exactly 125%
	7. Finally check the zoom level one more time
	"""
	
	model = ChatOpenAI(model='gpt-4o-mini')
	agent = Agent(task=task, llm=model, controller=controller)
	
	history = await agent.run()
	
	print("\n" + "="*50)
	print("ZOOM EXAMPLE COMPLETED")
	print("="*50)
	print(f"Final zoom level: {current_zoom_level * 100:.0f}%")
	print("\nThis example demonstrated:")
	print("- Zooming in and out")
	print("- Getting current zoom level")
	print("- Resetting zoom to default")
	print("- Setting specific zoom levels")
	print("- Zoom level validation and limits")


if __name__ == '__main__':
	asyncio.run(main())