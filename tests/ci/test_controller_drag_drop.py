import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	DragDropAction,
	GoToUrlAction,
)


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add routes for common test pages
	server.expect_request('/').respond_with_data(
		'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance with security disabled."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


@pytest.fixture(scope='function')
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestControllerDragDrop:
	"""Integration tests for Controller drag and drop functionality."""

	async def test_drag_drop_by_index(self, controller, browser_session, base_url, http_server):
		"""Test that drag_drop works correctly with index-based approach using a sortable list."""
		# Add route for drag and drop test page with sortable list
		http_server.expect_request('/dragdrop_index').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Drag Drop Index Test</title>
				<style>
					#sortable-list {
						list-style: none;
						padding: 0;
						margin: 20px;
					}
					.sortable-item {
						background: #f0f0f0;
						border: 2px solid #ddd;
						padding: 10px;
						margin: 5px 0;
						cursor: move;
						user-select: none;
						position: relative;
					}
					.sortable-item:hover {
						background: #e0e0e0;
					}
					.sortable-item.dragging {
						opacity: 0.5;
					}
					#result {
						margin: 20px;
						padding: 10px;
						border: 1px solid #ccc;
						background: #f9f9f9;
					}
				</style>
			</head>
			<body>
				<h1>Sortable List Test</h1>
				<ul id="sortable-list">
					<li class="sortable-item" draggable="true" data-id="item1">Item 1</li>
					<li class="sortable-item" draggable="true" data-id="item2">Item 2</li>
					<li class="sortable-item" draggable="true" data-id="item3">Item 3</li>
					<li class="sortable-item" draggable="true" data-id="item4">Item 4</li>
				</ul>
				<div id="result">Original order: item1, item2, item3, item4</div>
				
				<script>
					let draggedElement = null;
					let dropTarget = null;
					
					// Track drag and drop operations
					document.addEventListener('dragstart', function(e) {
						if (e.target.classList.contains('sortable-item')) {
							draggedElement = e.target;
							e.target.classList.add('dragging');
						}
					});
					
					document.addEventListener('dragend', function(e) {
						if (e.target.classList.contains('sortable-item')) {
							e.target.classList.remove('dragging');
						}
					});
					
					document.addEventListener('dragover', function(e) {
						e.preventDefault();
					});
					
					document.addEventListener('drop', function(e) {
						e.preventDefault();
						if (e.target.classList.contains('sortable-item') && draggedElement) {
							dropTarget = e.target;
							// Swap the elements
							const parent = draggedElement.parentNode;
							const draggedNext = draggedElement.nextSibling;
							const targetNext = dropTarget.nextSibling;
							
							if (draggedNext === dropTarget) {
								parent.insertBefore(dropTarget, draggedElement);
							} else if (targetNext === draggedElement) {
								parent.insertBefore(draggedElement, dropTarget);
							} else {
								parent.insertBefore(draggedElement, targetNext);
								parent.insertBefore(dropTarget, draggedNext);
							}
							
							updateResult();
						}
					});
					
					// Also handle mouse-based drag and drop for testing
					let isDragging = false;
					let startElement = null;
					
					document.addEventListener('mousedown', function(e) {
						if (e.target.classList.contains('sortable-item')) {
							isDragging = true;
							startElement = e.target;
							e.target.classList.add('dragging');
						}
					});
					
					document.addEventListener('mouseup', function(e) {
						if (isDragging && e.target.classList.contains('sortable-item') && startElement && startElement !== e.target) {
							// Perform the swap
							const parent = startElement.parentNode;
							const startNext = startElement.nextSibling;
							const targetNext = e.target.nextSibling;
							
							if (startNext === e.target) {
								parent.insertBefore(e.target, startElement);
							} else if (targetNext === startElement) {
								parent.insertBefore(startElement, e.target);
							} else {
								parent.insertBefore(startElement, targetNext);
								parent.insertBefore(e.target, startNext);
							}
							
							updateResult();
						}
						
						if (startElement) {
							startElement.classList.remove('dragging');
						}
						isDragging = false;
						startElement = null;
					});
					
					function updateResult() {
						const items = Array.from(document.querySelectorAll('.sortable-item'));
						const order = items.map(item => item.getAttribute('data-id')).join(', ');
						document.getElementById('result').textContent = 'Current order: ' + order;
					}
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the drag and drop test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/dragdrop_index', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		page = await browser_session.get_current_page()
		await page.wait_for_load_state()

		# Initialize the DOM state to populate the selector map
		await browser_session.get_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the sortable items in the selector map
		item1_index = 0
		item3_index = 2

		# Get the initial order
		initial_order = await page.evaluate("""
			() => {
				const items = Array.from(document.querySelectorAll('.sortable-item'));
				return items.map(item => item.getAttribute('data-id'));
			}
		""")
		assert initial_order == ['item1', 'item2', 'item3', 'item4'], f'Unexpected initial order: {initial_order}'

		# Give the page a moment to process the drag and drop
		# await page.wait_for_timeout(100000)

		# Create a model for the drag_drop action
		class DragDropActionModel(ActionModel):
			drag_drop: DragDropAction | None = None

		# Execute drag and drop from item1 to item3 (should swap their positions)
		drag_drop_action = DragDropAction(source_index=item1_index, target_index=item3_index, steps=5, delay_ms=10)
		result = await controller.act(DragDropActionModel(drag_drop=drag_drop_action), browser_session)

		# Verify the result structure
		assert isinstance(result, ActionResult), 'Result should be an ActionResult instance'
		assert result.error is None, f'Expected no error but got: {result.error}'

		# Verify the action was logged correctly
		assert result.extracted_content is not None
		assert f'element with index {item1_index}' in result.extracted_content
		assert f'element with index {item3_index}' in result.extracted_content

		# Give the page a moment to process the drag and drop
		await page.wait_for_timeout(100)

		# Verify the drag and drop actually changed the order
		final_order = await page.evaluate("""
			() => {
				const items = Array.from(document.querySelectorAll('.sortable-item'));
				return items.map(item => item.getAttribute('data-id'));
			}
		""")

		# The order should have changed - item1 and item3 should have swapped
		expected_order = ['item3', 'item2', 'item1', 'item4']
		assert final_order == expected_order, f'Expected order {expected_order}, got {final_order}'

		# Also verify the result text was updated
		result_text = await page.text_content('#result')
		assert 'item3, item2, item1, item4' in result_text, f'Result text not updated correctly: {result_text}'

	async def test_drag_drop_by_coordinates(self, controller, browser_session, base_url, http_server):
		"""Test that drag_drop works correctly with coordinate-based approach using a canvas."""
		# Add route for coordinate-based drag and drop test
		http_server.expect_request('/dragdrop_coords').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Drag Drop Coordinates Test</title>
				<style>
					#canvas {
						border: 2px solid #333;
						cursor: crosshair;
						display: block;
						margin: 20px auto;
					}
					#info {
						text-align: center;
						margin: 20px;
						font-family: Arial, sans-serif;
					}
					#drag-log {
						margin: 20px;
						padding: 10px;
						background: #f0f0f0;
						border: 1px solid #ccc;
						min-height: 50px;
						font-family: monospace;
					}
				</style>
			</head>
			<body>
				<div id="info">
					<h1>Canvas Drag Test</h1>
					<p>Canvas will track mouse drag operations</p>
				</div>
				<canvas id="canvas" width="400" height="300"></canvas>
				<div id="drag-log">Drag operations will be logged here...</div>
				
				<script>
					const canvas = document.getElementById('canvas');
					const ctx = canvas.getContext('2d');
					const dragLog = document.getElementById('drag-log');
					
					let isDrawing = false;
					let startX = 0;
					let startY = 0;
					let dragCount = 0;
					
					// Clear canvas and set up initial state
					ctx.fillStyle = '#f9f9f9';
					ctx.fillRect(0, 0, canvas.width, canvas.height);
					ctx.strokeStyle = '#333';
					ctx.lineWidth = 2;
					
					// Mouse event handlers
					canvas.addEventListener('mousedown', function(e) {
						const rect = canvas.getBoundingClientRect();
						startX = e.clientX - rect.left;
						startY = e.clientY - rect.top;
						isDrawing = true;
						
						// Draw start point
						ctx.beginPath();
						ctx.arc(startX, startY, 3, 0, 2 * Math.PI);
						ctx.fillStyle = '#ff0000';
						ctx.fill();
						
						logDrag('START', startX, startY);
					});
					
					canvas.addEventListener('mousemove', function(e) {
						if (!isDrawing) return;
						
						const rect = canvas.getBoundingClientRect();
						const currX = e.clientX - rect.left;
						const currY = e.clientY - rect.top;
						
						// Draw line from start to current position
						ctx.beginPath();
						ctx.moveTo(startX, startY);
						ctx.lineTo(currX, currY);
						ctx.strokeStyle = '#0066cc';
						ctx.stroke();
						
						logDrag('MOVE', currX, currY);
					});
					
					canvas.addEventListener('mouseup', function(e) {
						if (!isDrawing) return;
						
						const rect = canvas.getBoundingClientRect();
						const endX = e.clientX - rect.left;
						const endY = e.clientY - rect.top;
						
						// Draw end point
						ctx.beginPath();
						ctx.arc(endX, endY, 3, 0, 2 * Math.PI);
						ctx.fillStyle = '#00ff00';
						ctx.fill();
						
						isDrawing = false;
						dragCount++;
						
						logDrag('END', endX, endY);
						logDrag('COMPLETE', 0, 0, `Drag operation ${dragCount} completed`);
					});
					
					function logDrag(action, x, y, extra = '') {
						const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
						const message = `[${timestamp}] ${action}: (${Math.round(x)}, ${Math.round(y)}) ${extra}`;
						
						if (dragLog.textContent === 'Drag operations will be logged here...') {
							dragLog.textContent = message;
						} else {
							dragLog.textContent += '\\n' + message;
						}
					}
					
					// Expose drag count for testing
					window.getDragCount = function() {
						return dragCount;
					};
					
					window.getCanvasImageData = function() {
						return canvas.toDataURL();
					};
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the coordinate drag test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/dragdrop_coords', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		page = await browser_session.get_current_page()
		await page.wait_for_load_state()

		# Get the canvas element's position for coordinate calculation
		canvas_rect = await page.evaluate("""
			() => {
				const canvas = document.getElementById('canvas');
				const rect = canvas.getBoundingClientRect();
				return {
					x: rect.left,
					y: rect.top,
					width: rect.width,
					height: rect.height
				};
			}
		""")

		# Calculate coordinates for drag operation (drag from top-left to bottom-right of canvas)
		start_x = int(canvas_rect['x'] + 50)  # 50px from left edge of canvas
		start_y = int(canvas_rect['y'] + 50)  # 50px from top edge of canvas
		end_x = int(canvas_rect['x'] + canvas_rect['width'] - 50)  # 50px from right edge
		end_y = int(canvas_rect['y'] + canvas_rect['height'] - 50)  # 50px from bottom edge

		# Get initial state
		initial_drag_count = await page.evaluate('window.getDragCount()')
		initial_image = await page.evaluate('window.getCanvasImageData()')

		# Create a model for the drag_drop action
		class DragDropActionModel(ActionModel):
			drag_drop: DragDropAction | None = None

		# Execute coordinate-based drag and drop
		drag_drop_action = DragDropAction(
			coord_source_x=start_x,
			coord_source_y=start_y,
			coord_target_x=end_x,
			coord_target_y=end_y,
			steps=15,
			delay_ms=8,
		)
		result = await controller.act(DragDropActionModel(drag_drop=drag_drop_action), browser_session)

		# Verify the result structure
		assert isinstance(result, ActionResult), 'Result should be an ActionResult instance'
		assert result.error is None, f'Expected no error but got: {result.error}'

		# Verify the action was logged correctly
		assert result.extracted_content is not None
		assert f'({start_x}, {start_y})' in result.extracted_content
		assert f'({end_x}, {end_y})' in result.extracted_content

		# Give the page a moment to process the drag and drop
		await page.wait_for_timeout(200)

		# Verify the drag operation was detected
		final_drag_count = await page.evaluate('window.getDragCount()')
		assert final_drag_count > initial_drag_count, (
			f'Drag count should have increased from {initial_drag_count} to {final_drag_count}'
		)

		# Verify the canvas image changed (something was drawn)
		final_image = await page.evaluate('window.getCanvasImageData()')
		assert final_image != initial_image, 'Canvas should have changed after drag operation'

		# Verify the drag log contains our operation
		drag_log_text = await page.text_content('#drag-log')
		assert 'START:' in drag_log_text, 'Drag log should contain START event'
		assert 'END:' in drag_log_text, 'Drag log should contain END event'
		assert 'COMPLETE:' in drag_log_text, 'Drag log should contain COMPLETE event'
