"""
Drag and Drop Custom Action Example

This example demonstrates how to implement drag and drop functionality as a custom action.
The drag and drop action supports both element-based and coordinate-based operations,
making it useful for canvas drawing, sortable lists, sliders, file uploads, and UI rearrangement.
"""

import asyncio
from typing import cast

from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.session import BrowserSession
from browser_use.browser.types import Page
from browser_use.llm import ChatOpenAI


class DragDropAction(BaseModel):
	# Index-based approach (preferred)
	source_index: int | None = Field(default=None, description='Index of the element to drag from')
	target_index: int | None = Field(default=None, description='Index of the element to drop onto')

	# Coordinate-based approach (used if indices not provided)
	coord_source_x: int | None = Field(default=None, description='Source X coordinate for drag start')
	coord_source_y: int | None = Field(default=None, description='Source Y coordinate for drag start')
	coord_target_x: int | None = Field(default=None, description='Target X coordinate for drag end')
	coord_target_y: int | None = Field(default=None, description='Target Y coordinate for drag end')

	# Common options
	steps: int | None = Field(default=10, description='Number of intermediate steps during drag (default: 10)')
	delay_ms: int | None = Field(default=5, description='Delay in milliseconds between steps (default: 5)')


async def create_drag_drop_controller() -> Controller:
	"""Create a controller with drag and drop functionality."""
	controller = Controller()

	@controller.registry.action(
		'Drag and drop elements or between coordinates on the page - useful for canvas drawing, sortable lists, sliders, and UI rearrangement',
		param_model=DragDropAction,
	)
	async def drag_drop(params: DragDropAction, browser_session: BrowserSession) -> ActionResult:
		"""
		Performs a precise drag and drop operation between elements or coordinates.
		"""

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

			page = await browser_session.get_current_page()
			selector_map = await browser_session.get_selector_map()

			# Case 1: Index-based approach (preferred)
			if params.source_index is not None and params.target_index is not None:
				if params.source_index not in selector_map:
					raise Exception(f'Source element index {params.source_index} does not exist.')
				if params.target_index not in selector_map:
					raise Exception(f'Target element index {params.target_index} does not exist.')

				source_dom = selector_map[params.source_index]
				target_dom = selector_map[params.target_index]

				# Get elements using xpath from dom nodes
				source_element = await browser_session.get_locate_element_by_xpath(source_dom.xpath)
				target_element = await browser_session.get_locate_element_by_xpath(target_dom.xpath)

				assert source_element is not None, f'Could not locate source element with index {params.source_index}'
				assert target_element is not None, f'Could not locate target element with index {params.target_index}'

				# Get source coordinates
				source_box = await source_element.bounding_box()
				assert source_box is not None, f'Could not get bounding box for source element {params.source_index}'
				source_x = int(source_box['x'] + source_box['width'] / 2)
				source_y = int(source_box['y'] + source_box['height'] / 2)

				# Get target coordinates
				target_box = await target_element.bounding_box()
				assert target_box is not None, f'Could not get bounding box for target element {params.target_index}'
				target_x = int(target_box['x'] + target_box['width'] / 2)
				target_y = int(target_box['y'] + target_box['height'] / 2)

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

			# Case 3: Invalid parameters
			else:
				raise Exception('Must provide either source/target indices or source/target coordinates')

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
			if params.source_index is not None and params.target_index is not None:
				msg = f"🖱️ Dragged element '{params.source_index}' to '{params.target_index}'"
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
	llm = ChatOpenAI(model='gpt-4.1')

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
	llm = ChatOpenAI(model='gpt-4.1')

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

	choice = input('Enter choice (1-2): ').strip()

	if choice == '1':
		asyncio.run(example_drag_drop_sortable_list())
	elif choice == '2':
		asyncio.run(example_drag_drop_coordinates())

	else:
		print('Invalid choice, running sortable list example...')
		asyncio.run(example_drag_drop_sortable_list())
