"""
Browser Action Server implementation.

HTTP server that allows Claude Code sessions to control browsers through 
individual action commands without blocking the terminal.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from pydantic import ValidationError

from .views import (
	NavigateRequest, ClickRequest, TypeRequest, ScrollRequest, HoverRequest,
	WaitRequest, SelectRequest, UploadRequest,
	ActionResponse, ErrorResponse, PageStatusResponse, ScreenshotResponse,
	ElementInfoResponse, HealthResponse, ErrorDetail
)

logger = logging.getLogger(__name__)


class BrowserSessionManager:
	"""Manages browser session and Playwright integration"""
	
	def __init__(self):
		self.browser: Any = None
		self.context: Any = None
		self.page: Any = None
		self._start_time = time.time()
		self._request_count = 0
		
	async def ensure_browser(self) -> None:
		"""Ensure browser is running and page is available"""
		if self.browser is None:
			try:
				from playwright.async_api import async_playwright
				
				self.playwright = await async_playwright().start()
				self.browser = await self.playwright.chromium.launch(
					headless=False,  # Show browser for Claude Code usage
					args=['--no-sandbox', '--disable-web-security']
				)
				self.context = await self.browser.new_context()
				self.page = await self.context.new_page()
				
				logger.info("Browser session initialized successfully")
				
			except Exception as e:
				logger.error(f"Failed to initialize browser: {e}")
				raise RuntimeError(f"Browser initialization failed: {e}") from e
	
	async def close(self) -> None:
		"""Close browser session"""
		try:
			if self.page:
				await self.page.close()
			if self.context:
				await self.context.close()
			if self.browser:
				await self.browser.close()
			if hasattr(self, 'playwright'):
				await self.playwright.stop()
				
			logger.info("Browser session closed")
			
		except Exception as e:
			logger.error(f"Error closing browser: {e}")
	
	def increment_request_count(self) -> None:
		"""Track request count for monitoring"""
		self._request_count += 1
	
	@property
	def uptime_seconds(self) -> float:
		"""Get server uptime in seconds"""
		return time.time() - self._start_time
	
	@property
	def total_requests(self) -> int:
		"""Get total request count"""
		return self._request_count
	
	@property
	def is_connected(self) -> bool:
		"""Check if browser is connected"""
		return self.browser is not None and self.page is not None


class BrowserActionServer:
	"""
	HTTP server for browser automation actions.
	
	Provides REST API for Claude Code to control browsers through individual commands.
	"""
	
	def __init__(self, host: str = '127.0.0.1', port: int = 8766, debug: bool = False):
		self.host = host
		self.port = port
		self.debug = debug
		self.app: Any = None
		self.server_task: asyncio.Task | None = None
		self._logger = self._setup_logger()
		self._session = BrowserSessionManager()
		
	def _setup_logger(self) -> logging.Logger:
		"""Set up logging for the action server"""
		server_logger = logging.getLogger(f'{__name__}.server')
		
		if self.debug:
			server_logger.setLevel(logging.DEBUG)
		else:
			server_logger.setLevel(logging.INFO)
			
		return server_logger
	
	def _log_request(self, method: str, path: str, execution_time: float = 0.0) -> None:
		"""Log incoming requests"""
		self._logger.info(f'{method} {path} - {execution_time:.2f}ms')
	
	def _log_error(self, error: Exception, context: str = '') -> None:
		"""Log errors with context"""
		self._logger.error(f'Action Server Error{f" ({context})" if context else ""}: {error}', exc_info=True)
	
	async def start(self) -> None:
		"""Start the action server in background"""
		try:
			# Import FastAPI here to avoid dependency issues if not installed
			from fastapi import FastAPI, HTTPException
			from fastapi.responses import JSONResponse
			import uvicorn
			
			self.app = FastAPI(
				title="Browser Action Server",
				description="HTTP server for Claude Code browser automation",
				version="1.0.0",
				debug=self.debug
			)
			
			self._setup_routes()
			
			self._logger.info(f'Starting Browser Action Server on {self.host}:{self.port}')
			
			# Configure uvicorn
			config = uvicorn.Config(
				app=self.app,
				host=self.host,
				port=self.port,
				log_level="info" if self.debug else "warning",
				access_log=self.debug
			)
			
			server = uvicorn.Server(config)
			
			# Start server as background task
			self.server_task = asyncio.create_task(server.serve())
			
			# Give server time to start
			await asyncio.sleep(1.0)
			self._logger.info('Browser Action Server started successfully')
			
		except ImportError as e:
			self._log_error(e, 'FastAPI/uvicorn not available')
			raise RuntimeError('FastAPI and uvicorn are required. Install with: pip install fastapi uvicorn') from e
		except Exception as e:
			self._log_error(e, 'server startup')
			raise
	
	async def stop(self) -> None:
		"""Stop the action server"""
		self._logger.info('Stopping Browser Action Server...')
		
		# Close browser session
		await self._session.close()
		
		# Stop server task
		if self.server_task:
			self.server_task.cancel()
			try:
				await self.server_task
			except asyncio.CancelledError:
				pass
		
		self._logger.info('Browser Action Server stopped')
	
	def _setup_routes(self) -> None:
		"""Setup HTTP routes"""
		from fastapi import HTTPException
		from fastapi.responses import JSONResponse
		
		async def handle_request(handler_func, request_data=None):
			"""Common request handling wrapper"""
			start_time = time.time()
			self._session.increment_request_count()
			
			try:
				await self._session.ensure_browser()
				
				if request_data:
					result = await handler_func(request_data)
				else:
					result = await handler_func()
				
				execution_time = (time.time() - start_time) * 1000
				result.execution_time_ms = execution_time
				
				return result
				
			except Exception as e:
				execution_time = (time.time() - start_time) * 1000
				self._log_error(e, 'request handling')
				
				error_detail = ErrorDetail(
					type=type(e).__name__,
					message=str(e),
					details={'context': 'request_handling'},
					recoverable=True
				)
				
				return ErrorResponse(
					error=error_detail,
					execution_time_ms=execution_time
				)
		
		# Health check endpoint
		@self.app.get('/health')
		async def health_check():
			"""Get server health status"""
			self._log_request('GET', '/health')
			
			response = await handle_request(self._handle_health)
			return response.model_dump()
		
		# Navigation endpoints
		@self.app.post('/navigate')
		async def navigate(request: NavigateRequest):
			"""Navigate to URL"""
			self._log_request('POST', '/navigate')
			
			response = await handle_request(self._handle_navigate, request)
			return response.model_dump()
		
		@self.app.post('/reload')
		async def reload():
			"""Reload current page"""
			self._log_request('POST', '/reload')
			
			response = await handle_request(self._handle_reload)
			return response.model_dump()
		
		@self.app.post('/back')
		async def go_back():
			"""Go back in browser history"""
			self._log_request('POST', '/back')
			
			response = await handle_request(self._handle_back)
			return response.model_dump()
		
		@self.app.post('/forward')
		async def go_forward():
			"""Go forward in browser history"""
			self._log_request('POST', '/forward')
			
			response = await handle_request(self._handle_forward)
			return response.model_dump()
		
		# Interaction endpoints
		@self.app.post('/click')
		async def click(request: ClickRequest):
			"""Click element"""
			self._log_request('POST', '/click')
			
			response = await handle_request(self._handle_click, request)
			return response.model_dump()
		
		@self.app.post('/type')
		async def type_text(request: TypeRequest):
			"""Type text into element"""
			self._log_request('POST', '/type')
			
			response = await handle_request(self._handle_type, request)
			return response.model_dump()
		
		@self.app.post('/scroll')
		async def scroll(request: ScrollRequest):
			"""Scroll page or element"""
			self._log_request('POST', '/scroll')
			
			response = await handle_request(self._handle_scroll, request)
			return response.model_dump()
		
		@self.app.post('/hover')
		async def hover(request: HoverRequest):
			"""Hover over element"""
			self._log_request('POST', '/hover')
			
			response = await handle_request(self._handle_hover, request)
			return response.model_dump()
		
		@self.app.post('/wait')
		async def wait_for(request: WaitRequest):
			"""Wait for element or condition"""
			self._log_request('POST', '/wait')
			
			response = await handle_request(self._handle_wait, request)
			return response.model_dump()
		
		# Information endpoints
		@self.app.get('/status')
		async def get_status():
			"""Get current page status"""
			self._log_request('GET', '/status')
			
			response = await handle_request(self._handle_status)
			return response.model_dump()
		
		@self.app.get('/screenshot')
		async def take_screenshot():
			"""Take page screenshot"""
			self._log_request('GET', '/screenshot')
			
			response = await handle_request(self._handle_screenshot)
			return response.model_dump()
		
		@self.app.get('/html')
		async def get_html():
			"""Get page HTML"""
			self._log_request('GET', '/html')
			
			response = await handle_request(self._handle_html)
			return response.model_dump()
		
		@self.app.get('/element')
		async def get_element_info(selector: str):
			"""Get element information"""
			self._log_request('GET', f'/element?selector={selector}')
			
			response = await handle_request(self._handle_element_info, selector)
			return response.model_dump()
	
	# Action handlers
	
	async def _handle_health(self) -> HealthResponse:
		"""Handle health check request"""
		return HealthResponse.create(
			status='healthy',
			version='1.0.0',
			browser_connected=self._session.is_connected,
			uptime_seconds=self._session.uptime_seconds,
			total_requests=self._session.total_requests
		)
	
	async def _handle_navigate(self, request: NavigateRequest) -> ActionResponse:
		"""Handle navigation request"""
		page = self._session.page
		
		await page.goto(request.url, wait_until=request.wait_until, timeout=request.timeout * 1000)
		
		if request.wait_for_load:
			await page.wait_for_load_state('domcontentloaded')
		
		title = await page.title()
		url = page.url
		
		return ActionResponse(
			data={
				'url': url,
				'title': title,
				'requested_url': request.url,
				'wait_until': request.wait_until
			},
			message=f'Navigated to: {title} ({url})'
		)
	
	async def _handle_reload(self) -> ActionResponse:
		"""Handle page reload request"""
		page = self._session.page
		
		await page.reload(wait_until='domcontentloaded')
		
		title = await page.title()
		url = page.url
		
		return ActionResponse(
			data={
				'url': url,
				'title': title,
				'action': 'reload'
			},
			message=f'Page reloaded: {title}'
		)
	
	async def _handle_back(self) -> ActionResponse:
		"""Handle go back request"""
		page = self._session.page
		
		await page.go_back(wait_until='domcontentloaded')
		
		title = await page.title()
		url = page.url
		
		return ActionResponse(
			data={
				'url': url,
				'title': title,
				'action': 'back'
			},
			message=f'Went back to: {title}'
		)
	
	async def _handle_forward(self) -> ActionResponse:
		"""Handle go forward request"""
		page = self._session.page
		
		await page.go_forward(wait_until='domcontentloaded')
		
		title = await page.title()
		url = page.url
		
		return ActionResponse(
			data={
				'url': url,
				'title': title,
				'action': 'forward'
			},
			message=f'Went forward to: {title}'
		)
	
	async def _handle_click(self, request: ClickRequest) -> ActionResponse:
		"""Handle click request"""
		page = self._session.page
		
		element = page.locator(request.selector)
		
		# Wait for element to be visible
		await element.wait_for(state='visible', timeout=request.timeout * 1000)
		
		click_options = {
			'button': request.button,
			'click_count': request.click_count,
			'timeout': request.timeout * 1000
		}
		
		if request.position:
			click_options['position'] = {'x': request.position[0], 'y': request.position[1]}
		
		await element.click(**click_options)
		
		# Get element info after click
		element_info = await element.evaluate('''(el) => ({
			tagName: el.tagName,
			id: el.id,
			className: el.className,
			textContent: el.textContent?.slice(0, 100)
		})''')
		
		return ActionResponse(
			data={
				'selector': request.selector,
				'button': request.button,
				'click_count': request.click_count,
				'element': element_info
			},
			message=f'Clicked element: {request.selector}'
		)
	
	async def _handle_type(self, request: TypeRequest) -> ActionResponse:
		"""Handle type text request"""
		page = self._session.page
		
		element = page.locator(request.selector)
		
		# Wait for element to be visible
		await element.wait_for(state='visible', timeout=request.timeout * 1000)
		
		if request.clear_first:
			await element.clear()
		
		type_options = {'timeout': request.timeout * 1000}
		if request.delay > 0:
			type_options['delay'] = request.delay * 1000
		
		await element.type(request.text, **type_options)
		
		# Get current value
		current_value = await element.input_value() if await element.evaluate('el => el.tagName === "INPUT" || el.tagName === "TEXTAREA"') else await element.text_content()
		
		return ActionResponse(
			data={
				'selector': request.selector,
				'text': request.text,
				'cleared_first': request.clear_first,
				'current_value': current_value
			},
			message=f'Typed text into: {request.selector}'
		)
	
	async def _handle_scroll(self, request: ScrollRequest) -> ActionResponse:
		"""Handle scroll request"""
		page = self._session.page
		
		# Calculate scroll delta based on direction
		delta_map = {
			'up': (0, -request.amount),
			'down': (0, request.amount), 
			'left': (-request.amount, 0),
			'right': (request.amount, 0)
		}
		
		delta_x, delta_y = delta_map[request.direction]
		
		if request.selector:
			# Scroll specific element
			element = page.locator(request.selector)
			await element.scroll_into_view_if_needed()
			await element.evaluate(f'''(el) => {{
				el.scrollBy({{
					left: {delta_x},
					top: {delta_y},
					behavior: "{'smooth' if request.smooth else 'auto'}"
				}});
			}}''')
		else:
			# Scroll page
			await page.evaluate(f'''() => {{
				window.scrollBy({{
					left: {delta_x},
					top: {delta_y},
					behavior: "{'smooth' if request.smooth else 'auto'}"
				}});
			}}''')
		
		# Get current scroll position
		scroll_pos = await page.evaluate('() => ({ x: window.scrollX, y: window.scrollY })')
		
		return ActionResponse(
			data={
				'direction': request.direction,
				'amount': request.amount,
				'selector': request.selector,
				'scroll_position': scroll_pos
			},
			message=f'Scrolled {request.direction} by {request.amount}px'
		)
	
	async def _handle_hover(self, request: HoverRequest) -> ActionResponse:
		"""Handle hover request"""
		page = self._session.page
		
		element = page.locator(request.selector)
		await element.wait_for(state='visible', timeout=request.timeout * 1000)
		
		hover_options = {'timeout': request.timeout * 1000}
		if request.position:
			hover_options['position'] = {'x': request.position[0], 'y': request.position[1]}
		
		await element.hover(**hover_options)
		
		return ActionResponse(
			data={
				'selector': request.selector,
				'position': request.position
			},
			message=f'Hovered over: {request.selector}'
		)
	
	async def _handle_wait(self, request: WaitRequest) -> ActionResponse:
		"""Handle wait request"""
		page = self._session.page
		
		if request.condition_type == 'element':
			element = page.locator(request.selector)
			state = 'visible' if request.visible else 'attached'
			await element.wait_for(state=state, timeout=request.timeout * 1000)
			
			return ActionResponse(
				data={
					'condition_type': 'element',
					'selector': request.selector,
					'visible': request.visible
				},
				message=f'Element found: {request.selector}'
			)
		
		elif request.condition_type == 'text':
			await page.wait_for_function(
				f'() => document.body.textContent.includes("{request.text}")',
				timeout=request.timeout * 1000
			)
			
			return ActionResponse(
				data={
					'condition_type': 'text',
					'text': request.text
				},
				message=f'Text found: {request.text}'
			)
		
		elif request.condition_type == 'url':
			await page.wait_for_url(request.url, timeout=request.timeout * 1000)
			
			return ActionResponse(
				data={
					'condition_type': 'url',
					'url': request.url,
					'current_url': page.url
				},
				message=f'URL matched: {request.url}'
			)
		
		elif request.condition_type == 'timeout':
			await asyncio.sleep(request.timeout)
			
			return ActionResponse(
				data={
					'condition_type': 'timeout',
					'timeout': request.timeout
				},
				message=f'Waited for {request.timeout} seconds'
			)
		
		else:
			raise ValueError(f'Unknown condition type: {request.condition_type}')
	
	async def _handle_status(self) -> PageStatusResponse:
		"""Handle page status request"""
		page = self._session.page
		
		url = page.url
		title = await page.title()
		
		# Get page info
		page_info = await page.evaluate('''() => ({
			readyState: document.readyState,
			elementCount: document.querySelectorAll('*').length,
			viewport: {
				width: window.innerWidth,
				height: window.innerHeight
			},
			scroll: {
				x: window.scrollX,
				y: window.scrollY
			}
		})''')
		
		return PageStatusResponse.create(
			url=url,
			title=title,
			loading=page_info['readyState'] != 'complete',
			ready_state=page_info['readyState'],
			viewport_size=(page_info['viewport']['width'], page_info['viewport']['height']),
			scroll_position=(page_info['scroll']['x'], page_info['scroll']['y']),
			element_count=page_info['elementCount']
		)
	
	async def _handle_screenshot(self) -> ScreenshotResponse:
		"""Handle screenshot request"""
		page = self._session.page
		
		screenshot_bytes = await page.screenshot(type='png', full_page=False)
		screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
		
		# Get viewport size
		viewport = await page.evaluate('() => ({ width: window.innerWidth, height: window.innerHeight })')
		
		return ScreenshotResponse.create(
			screenshot_base64=screenshot_b64,
			format='png',
			size=(viewport['width'], viewport['height'])
		)
	
	async def _handle_html(self) -> ActionResponse:
		"""Handle get HTML request"""
		page = self._session.page
		
		html_content = await page.content()
		
		return ActionResponse(
			data={
				'html': html_content,
				'length': len(html_content),
				'url': page.url
			},
			message=f'Retrieved HTML content ({len(html_content)} characters)'
		)
	
	async def _handle_element_info(self, selector: str) -> ElementInfoResponse:
		"""Handle element info request"""
		page = self._session.page
		
		try:
			element = page.locator(selector)
			
			# Check if element exists
			count = await element.count()
			if count == 0:
				return ElementInfoResponse.create(
					selector=selector,
					found=False
				)
			
			# Get element information
			element_info = await element.first.evaluate('''(el) => ({
				tagName: el.tagName,
				id: el.id,
				className: el.className,
				textContent: el.textContent?.slice(0, 200),
				attributes: Array.from(el.attributes).reduce((acc, attr) => {
					acc[attr.name] = attr.value;
					return acc;
				}, {}),
				boundingBox: el.getBoundingClientRect(),
				visible: el.offsetParent !== null
			})''')
			
			return ElementInfoResponse.create(
				selector=selector,
				found=True,
				element_info=element_info
			)
			
		except Exception as e:
			return ElementInfoResponse.create(
				selector=selector,
				found=False,
				element_info={'error': str(e)}
			)