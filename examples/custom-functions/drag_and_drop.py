"""
Drag and Drop Custom Action Example

This example demonstrates how to implement drag and drop functionality as a custom action.
The drag and drop action supports both element-based and coordinate-based operations,
making it useful for canvas drawing, sortable lists, sliders, file uploads, and UI rearrangement.
"""

import asyncio
from typing import cast

from playwright.async_api import ElementHandle, Page
from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, Controller
from browser_use.llm import ChatOpenAI


class Position(BaseModel):
	"""Represents a position with x and y coordinates."""

	x: int = Field(..., description='X coordinate')
	y: int = Field(..., description='Y coordinate')


class DragDropAction(BaseModel):
	"""Parameters for drag and drop operations."""

	# Element-based approach
	element_source: str | None = Field(None, description='CSS selector or XPath for the source element to drag')
	element_target: str | None = Field(None, description='CSS selector or XPath for the target element to drop on')
	element_source_offset: Position | None = Field(None, description='Optional offset from source element center (x, y)')
	element_target_offset: Position | None = Field(None, description='Optional offset from target element center (x, y)')

	# Coordinate-based approach
	coord_source_x: int | None = Field(None, description='Source X coordinate for drag start')
	coord_source_y: int | None = Field(None, description='Source Y coordinate for drag start')
	coord_target_x: int | None = Field(None, description='Target X coordinate for drag end')
	coord_target_y: int | None = Field(None, description='Target Y coordinate for drag end')

	# Operation parameters
	steps: int | None = Field(10, description='Number of intermediate steps during drag (default: 10)')
	delay_ms: int | None = Field(5, description='Delay in milliseconds between steps (default: 5)')


async def create_drag_drop_controller() -> Controller:
	"""Create a controller with drag and drop functionality."""
	controller = Controller()

	@controller.registry.action(
		'Drag and drop elements or between coordinates on the page - useful for canvas drawing, sortable lists, sliders, file uploads, and UI rearrangement',
		param_model=DragDropAction,
	)
	async def drag_drop(params: DragDropAction, page: Page) -> ActionResult:
		"""
		Performs a precise drag and drop operation between elements or coordinates.
		"""

		async def get_drag_elements(
			page: Page,
			source_selector: str,
			target_selector: str,
		) -> tuple[ElementHandle | None, ElementHandle | None]:
			"""Get source and target elements with appropriate error handling."""
			source_element = None
			target_element = None

			try:
				# page.locator() auto-detects CSS and XPath
				source_locator = page.locator(source_selector)
				target_locator = page.locator(target_selector)

				# Check if elements exist
				source_count = await source_locator.count()
				target_count = await target_locator.count()

				if source_count > 0:
					source_element = await source_locator.first.element_handle()
					print(f'Found source element with selector: {source_selector}')
				else:
					print(f'Source element not found: {source_selector}')

				if target_count > 0:
					target_element = await target_locator.first.element_handle()
					print(f'Found target element with selector: {target_selector}')
				else:
					print(f'Target element not found: {target_selector}')

			except Exception as e:
				print(f'Error finding elements: {str(e)}')

			return source_element, target_element

		async def get_element_coordinates(
			source_element: ElementHandle,
			target_element: ElementHandle,
			source_position: Position | None,
			target_position: Position | None,
		) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
			"""Get coordinates from elements with appropriate error handling."""
			source_coords = None
			target_coords = None

			try:
				# Get source coordinates
				if source_position:
					source_coords = (source_position.x, source_position.y)
				else:
					source_box = await source_element.bounding_box()
					if source_box:
						source_coords = (
							int(source_box['x'] + source_box['width'] / 2),
							int(source_box['y'] + source_box['height'] / 2),
						)

				# Get target coordinates
				if target_position:
					target_coords = (target_position.x, target_position.y)
				else:
					target_box = await target_element.bounding_box()
					if target_box:
						target_coords = (
							int(target_box['x'] + target_box['width'] / 2),
							int(target_box['y'] + target_box['height'] / 2),
						)
			except Exception as e:
				print(f'Error getting element coordinates: {str(e)}')

			return source_coords, target_coords

		async def execute_drag_operation(
			page: Page,
			source_x: int,
			source_y: int,
			target_x: int,
			target_y: int,
			steps: int,
			delay_ms: int,
		) -> tuple[bool, str]:
			"""Execute the drag operation with comprehensive error handling."""
			try:
				# Try to move to source position
				try:
					await page.mouse.move(source_x, source_y)
					print(f'Moved to source position ({source_x}, {source_y})')
				except Exception as e:
					print(f'Failed to move to source position: {str(e)}')
					return False, f'Failed to move to source position: {str(e)}'

				# Press mouse button down
				await page.mouse.down()

				# Move to target position with intermediate steps
				for i in range(1, steps + 1):
					ratio = i / steps
					intermediate_x = int(source_x + (target_x - source_x) * ratio)
					intermediate_y = int(source_y + (target_y - source_y) * ratio)

					await page.mouse.move(intermediate_x, intermediate_y)

					if delay_ms > 0:
						await asyncio.sleep(delay_ms / 1000)

				# Move to final target position
				await page.mouse.move(target_x, target_y)

				# Move again to ensure dragover events are properly triggered
				await page.mouse.move(target_x, target_y)

				# Release mouse button
				await page.mouse.up()

				return True, 'Drag operation completed successfully'

			except Exception as e:
				return False, f'Error during drag operation: {str(e)}'

		try:
			# Initialize variables
			source_x: int | None = None
			source_y: int | None = None
			target_x: int | None = None
			target_y: int | None = None

			# Normalize parameters
			steps = max(1, params.steps or 10)
			delay_ms = max(0, params.delay_ms or 5)

			# Case 1: Element selectors provided
			if params.element_source and params.element_target:
				print('Using element-based approach with selectors')

				source_element, target_element = await get_drag_elements(
					page,
					params.element_source,
					params.element_target,
				)

				if not source_element or not target_element:
					error_msg = f'Failed to find {"source" if not source_element else "target"} element'
					return ActionResult(error=error_msg, include_in_memory=True)

				source_coords, target_coords = await get_element_coordinates(
					source_element, target_element, params.element_source_offset, params.element_target_offset
				)

				if not source_coords or not target_coords:
					error_msg = f'Failed to determine {"source" if not source_coords else "target"} coordinates'
					return ActionResult(error=error_msg, include_in_memory=True)

				source_x, source_y = source_coords
				target_x, target_y = target_coords

			# Case 2: Coordinates provided directly
			elif all(
				coord is not None
				for coord in [params.coord_source_x, params.coord_source_y, params.coord_target_x, params.coord_target_y]
			):
				print('Using coordinate-based approach')
				source_x = params.coord_source_x
				source_y = params.coord_source_y
				target_x = params.coord_target_x
				target_y = params.coord_target_y
			else:
				error_msg = 'Must provide either source/target selectors or source/target coordinates'
				return ActionResult(error=error_msg, include_in_memory=True)

			# Validate coordinates
			if any(coord is None for coord in [source_x, source_y, target_x, target_y]):
				error_msg = 'Failed to determine source or target coordinates'
				return ActionResult(error=error_msg, include_in_memory=True)

			# Perform the drag operation
			success, message = await execute_drag_operation(
				page,
				cast(int, source_x),
				cast(int, source_y),
				cast(int, target_x),
				cast(int, target_y),
				steps,
				delay_ms,
			)

			if not success:
				print(f'Drag operation failed: {message}')
				return ActionResult(error=message, include_in_memory=True)

			# Create descriptive message
			if params.element_source and params.element_target:
				msg = f"🖱️ Dragged element '{params.element_source}' to '{params.element_target}'"
			else:
				msg = f'🖱️ Dragged from ({source_x}, {source_y}) to ({target_x}, {target_y})'

			print(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

		except Exception as e:
			error_msg = f'Failed to perform drag and drop: {str(e)}'
			print(error_msg)
			return ActionResult(error=error_msg, include_in_memory=True)

	return controller


async def example_drag_drop_sortable_list():
	"""Example: Drag and drop to reorder items in a sortable list."""

	controller = await create_drag_drop_controller()

	# Initialize LLM (replace with your preferred model)
	llm = ChatOpenAI(model='gpt-4o')

	# Create the agent
	agent = Agent(
		task='Go to a drag and drop demo website and reorder some list items using drag and drop',
		llm=llm,
		controller=controller,
	)

	# Run the agent
	print('🚀 Starting drag and drop example...')
	history = await agent.run()

	return history


async def example_drag_drop_coordinates():
	"""Example: Direct coordinate-based drag and drop."""

	controller = await create_drag_drop_controller()
	llm = ChatOpenAI(model='gpt-4o')

	agent = Agent(
		task='Go to a canvas drawing website and draw a simple line using drag and drop from coordinates (100, 100) to (300, 200)',
		llm=llm,
		controller=controller,
	)

	print('🎨 Starting coordinate-based drag and drop example...')
	history = await agent.run()

	return history


if __name__ == '__main__':
	# Run different examples
	print('Choose an example:')
	print('1. Sortable list drag and drop')
	print('2. Coordinate-based drawing')

	choice = input('Enter choice (1-3): ').strip()

	if choice == '1':
		asyncio.run(example_drag_drop_sortable_list())
	elif choice == '2':
		asyncio.run(example_drag_drop_coordinates())

	else:
		print('Invalid choice, running sortable list example...')
		asyncio.run(example_drag_drop_sortable_list())
