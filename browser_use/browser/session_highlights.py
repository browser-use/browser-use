"""Highlight and coordinate helpers for BrowserSession."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import TYPE_CHECKING, Any

from browser_use.dom.views import DOMRect
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession
	from browser_use.dom.views import EnhancedDOMTreeNode


class BrowserSessionHighlightMixin:
	"""CDP coordinate lookup and visual highlight helpers."""

	async def remove_highlights(self: Any) -> None:
		"""Remove highlights from the page using CDP."""
		if not self.browser_profile.highlight_elements and not self.browser_profile.dom_highlight_elements:
			return

		try:
			async with asyncio.timeout(3.0):
				cdp_session = await self.get_or_create_cdp_session()

				script = """
				(function() {
					const highlights = document.querySelectorAll('[data-browser-use-highlight]');
					console.log('Removing', highlights.length, 'browser-use highlight elements');
					highlights.forEach(el => el.remove());

					const highlightContainer = document.getElementById('browser-use-debug-highlights');
					if (highlightContainer) {
						console.log('Removing highlight container by ID');
						highlightContainer.remove();
					}

					const orphanedTooltips = document.querySelectorAll('[data-browser-use-highlight="tooltip"]');
					orphanedTooltips.forEach(el => el.remove());

					return { removed: highlights.length };
				})();
				"""
				result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
				)

				if result and 'result' in result and 'value' in result['result']:
					removed_count = result['result']['value'].get('removed', 0)
					self.logger.debug(f'Successfully removed {removed_count} highlight elements')
				else:
					self.logger.debug('Highlight removal completed')

		except Exception as e:
			self.logger.warning(f'Failed to remove highlights: {e}')

	@observe_debug(ignore_input=True, ignore_output=True, name='get_element_coordinates')
	async def get_element_coordinates(self: Any, backend_node_id: int, cdp_session: CDPSession) -> DOMRect | None:
		"""Get element coordinates for a backend node ID using multiple methods."""
		session_id = cdp_session.session_id
		quads = []

		try:
			content_quads_result = await cdp_session.cdp_client.send.DOM.getContentQuads(
				params={'backendNodeId': backend_node_id}, session_id=session_id
			)
			if 'quads' in content_quads_result and content_quads_result['quads']:
				quads = content_quads_result['quads']
				self.logger.debug(f'Got {len(quads)} quads from DOM.getContentQuads')
			else:
				self.logger.debug(f'No quads found from DOM.getContentQuads {content_quads_result}')
		except Exception as e:
			self.logger.debug(f'DOM.getContentQuads failed: {e}')

		if not quads:
			try:
				box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
					params={'backendNodeId': backend_node_id}, session_id=session_id
				)
				if 'model' in box_model and 'content' in box_model['model']:
					content_quad = box_model['model']['content']
					if len(content_quad) >= 8:
						quads = [
							[
								content_quad[0],
								content_quad[1],
								content_quad[2],
								content_quad[3],
								content_quad[4],
								content_quad[5],
								content_quad[6],
								content_quad[7],
							]
						]
						self.logger.debug('Got quad from DOM.getBoxModel')
			except Exception as e:
				self.logger.debug(f'DOM.getBoxModel failed: {e}')

		if not quads:
			try:
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=session_id,
				)
				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					js_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'objectId': object_id,
							'functionDeclaration': """
							function() {
								const rect = this.getBoundingClientRect();
								return {
									x: rect.x,
									y: rect.y,
									width: rect.width,
									height: rect.height
								};
							}
							""",
							'returnByValue': True,
						},
						session_id=session_id,
					)
					if 'result' in js_result and 'value' in js_result['result']:
						rect_data = js_result['result']['value']
						if rect_data['width'] > 0 and rect_data['height'] > 0:
							return DOMRect(
								x=rect_data['x'], y=rect_data['y'], width=rect_data['width'], height=rect_data['height']
							)
			except Exception as e:
				self.logger.debug(f'JavaScript getBoundingClientRect failed: {e}')

		if quads:
			quad = quads[0]
			if len(quad) >= 8:
				x_coords = [quad[i] for i in range(0, 8, 2)]
				y_coords = [quad[i] for i in range(1, 8, 2)]

				min_x = min(x_coords)
				min_y = min(y_coords)
				max_x = max(x_coords)
				max_y = max(y_coords)

				width = max_x - min_x
				height = max_y - min_y

				if width > 0 and height > 0:
					return DOMRect(x=min_x, y=min_y, width=width, height=height)

		return None

	async def highlight_interaction_element(self: Any, node: EnhancedDOMTreeNode) -> None:
		"""Temporarily highlight an element during interaction for user visibility."""
		if not self.browser_profile.highlight_elements:
			return

		try:
			cdp_session = await self.get_or_create_cdp_session()
			rect = await self.get_element_coordinates(node.backend_node_id, cdp_session)

			color = self.browser_profile.interaction_highlight_color
			duration_ms = int(self.browser_profile.interaction_highlight_duration * 1000)

			if not rect:
				self.logger.debug(f'No coordinates found for backend node {node.backend_node_id}')
				return

			script = f"""
			(function() {{
				const rect = {json.dumps({'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height})};
				const color = {json.dumps(color)};
				const duration = {duration_ms};

				const maxCornerSize = 20;
				const minCornerSize = 8;
				const cornerSize = Math.max(
					minCornerSize,
					Math.min(maxCornerSize, Math.min(rect.width, rect.height) * 0.35)
				);
				const borderWidth = 3;
				const startOffset = 10;
				const finalOffset = -3;

				const scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0;
				const scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;

				const container = document.createElement('div');
				container.setAttribute('data-browser-use-interaction-highlight', 'true');
				container.style.cssText = `
					position: absolute;
					left: ${{rect.x + scrollX}}px;
					top: ${{rect.y + scrollY}}px;
					width: ${{rect.width}}px;
					height: ${{rect.height}}px;
					pointer-events: none;
					z-index: 2147483647;
				`;

				const corners = [
					{{ pos: 'top-left', startX: -startOffset, startY: -startOffset, finalX: finalOffset, finalY: finalOffset }},
					{{ pos: 'top-right', startX: startOffset, startY: -startOffset, finalX: -finalOffset, finalY: finalOffset }},
					{{ pos: 'bottom-left', startX: -startOffset, startY: startOffset, finalX: finalOffset, finalY: -finalOffset }},
					{{ pos: 'bottom-right', startX: startOffset, startY: startOffset, finalX: -finalOffset, finalY: -finalOffset }}
				];

				corners.forEach(corner => {{
					const bracket = document.createElement('div');
					bracket.style.cssText = `
						position: absolute;
						width: ${{cornerSize}}px;
						height: ${{cornerSize}}px;
						pointer-events: none;
						transition: all 0.15s ease-out;
					`;

					if (corner.pos === 'top-left') {{
						bracket.style.top = '0';
						bracket.style.left = '0';
						bracket.style.borderTop = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderLeft = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'top-right') {{
						bracket.style.top = '0';
						bracket.style.right = '0';
						bracket.style.borderTop = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderRight = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'bottom-left') {{
						bracket.style.bottom = '0';
						bracket.style.left = '0';
						bracket.style.borderBottom = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderLeft = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'bottom-right') {{
						bracket.style.bottom = '0';
						bracket.style.right = '0';
						bracket.style.borderBottom = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderRight = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}}

					container.appendChild(bracket);

					setTimeout(() => {{
						bracket.style.transform = `translate(${{corner.finalX}}px, ${{corner.finalY}}px)`;
					}}, 10);
				}});

				document.body.appendChild(container);

				setTimeout(() => {{
					container.style.opacity = '0';
					container.style.transition = 'opacity 0.3s ease-out';
					setTimeout(() => container.remove(), 300);
				}}, duration);

				return {{ created: true }};
			}})();
			"""

			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

		except Exception as e:
			self.logger.debug(f'Failed to highlight interaction element: {e}')

	async def highlight_coordinate_click(self: Any, x: int, y: int) -> None:
		"""Temporarily highlight a coordinate click position for user visibility."""
		if not self.browser_profile.highlight_elements:
			return

		try:
			cdp_session = await self.get_or_create_cdp_session()

			color = self.browser_profile.interaction_highlight_color
			duration_ms = int(self.browser_profile.interaction_highlight_duration * 1000)

			script = f"""
			(function() {{
				const x = {x};
				const y = {y};
				const color = {json.dumps(color)};
				const duration = {duration_ms};

				const scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0;
				const scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;

				const container = document.createElement('div');
				container.setAttribute('data-browser-use-coordinate-highlight', 'true');
				container.style.cssText = `
					position: absolute;
					left: ${{x + scrollX}}px;
					top: ${{y + scrollY}}px;
					width: 0;
					height: 0;
					pointer-events: none;
					z-index: 2147483647;
				`;

				const outerCircle = document.createElement('div');
				outerCircle.style.cssText = `
					position: absolute;
					left: -15px;
					top: -15px;
					width: 30px;
					height: 30px;
					border: 3px solid ${{color}};
					border-radius: 50%;
					opacity: 0;
					transform: scale(0.3);
					transition: all 0.2s ease-out;
				`;
				container.appendChild(outerCircle);

				const centerDot = document.createElement('div');
				centerDot.style.cssText = `
					position: absolute;
					left: -4px;
					top: -4px;
					width: 8px;
					height: 8px;
					background: ${{color}};
					border-radius: 50%;
					opacity: 0;
					transform: scale(0);
					transition: all 0.15s ease-out;
				`;
				container.appendChild(centerDot);

				document.body.appendChild(container);

				setTimeout(() => {{
					outerCircle.style.opacity = '0.8';
					outerCircle.style.transform = 'scale(1)';
					centerDot.style.opacity = '1';
					centerDot.style.transform = 'scale(1)';
				}}, 10);

				setTimeout(() => {{
					outerCircle.style.opacity = '0';
					outerCircle.style.transform = 'scale(1.5)';
					centerDot.style.opacity = '0';
					setTimeout(() => container.remove(), 300);
				}}, duration);

				return {{ created: true }};
			}})();
			"""

			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

		except Exception as e:
			self.logger.debug(f'Failed to highlight coordinate click: {e}')

	async def add_highlights(self: Any, selector_map: dict[int, EnhancedDOMTreeNode]) -> None:
		"""Add visual highlights to the browser DOM for user visibility."""
		if not self.browser_profile.dom_highlight_elements or not selector_map:
			return

		try:
			elements_data = []
			for _, node in selector_map.items():
				if node.absolute_position:
					rect = node.absolute_position
					bbox = {'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height}

					if bbox and bbox.get('width', 0) > 0 and bbox.get('height', 0) > 0:
						element = {
							'x': bbox['x'],
							'y': bbox['y'],
							'width': bbox['width'],
							'height': bbox['height'],
							'element_name': node.node_name,
							'is_clickable': node.snapshot_node.is_clickable if node.snapshot_node else True,
							'is_scrollable': getattr(node, 'is_scrollable', False),
							'attributes': node.attributes or {},
							'frame_id': getattr(node, 'frame_id', None),
							'node_id': node.node_id,
							'backend_node_id': node.backend_node_id,
							'xpath': node.xpath,
							'text_content': node.get_all_children_text()[:50]
							if hasattr(node, 'get_all_children_text')
							else node.node_value[:50],
						}
						elements_data.append(element)

			if not elements_data:
				self.logger.debug('No valid elements to highlight')
				return

			self.logger.debug(f'Creating highlights for {len(elements_data)} elements')

			await self.remove_highlights()
			await asyncio.sleep(0.05)

			cdp_session = await self.get_or_create_cdp_session()

			script = f"""
			(function() {{
				const interactiveElements = {json.dumps(elements_data)};

				console.log('=== BROWSER-USE HIGHLIGHTING ===');
				console.log('Highlighting', interactiveElements.length, 'interactive elements');

				const existingContainer = document.getElementById('browser-use-debug-highlights');
				if (existingContainer) {{
					console.log('Found existing highlight container, removing it first');
					existingContainer.remove();
				}}

				const strayHighlights = document.querySelectorAll('[data-browser-use-highlight]');
				if (strayHighlights.length > 0) {{
					console.log('Found', strayHighlights.length, 'stray highlight elements, removing them');
					strayHighlights.forEach(el => el.remove());
				}}

				const HIGHLIGHT_Z_INDEX = 2147483647;

				const container = document.createElement('div');
				container.id = 'browser-use-debug-highlights';
				container.setAttribute('data-browser-use-highlight', 'container');

				container.style.cssText = `
					position: absolute;
					top: 0;
					left: 0;
					width: 100vw;
					height: 100vh;
					pointer-events: none;
					z-index: ${{HIGHLIGHT_Z_INDEX}};
					overflow: visible;
					margin: 0;
					padding: 0;
					border: none;
					outline: none;
					box-shadow: none;
					background: none;
					font-family: inherit;
				`;

				function createTextElement(tag, text, styles) {{
					const element = document.createElement(tag);
					element.textContent = text;
					if (styles) element.style.cssText = styles;
					return element;
				}}

				interactiveElements.forEach((element, index) => {{
					const highlight = document.createElement('div');
					highlight.setAttribute('data-browser-use-highlight', 'element');
					highlight.setAttribute('data-element-id', element.backend_node_id);
					highlight.style.cssText = `
						position: absolute;
						left: ${{element.x}}px;
						top: ${{element.y}}px;
						width: ${{element.width}}px;
						height: ${{element.height}}px;
						outline: 2px dashed #4a90e2;
						outline-offset: -2px;
						background: transparent;
						pointer-events: none;
						box-sizing: content-box;
						transition: outline 0.2s ease;
						margin: 0;
						padding: 0;
						border: none;
					`;

					const label = createTextElement('div', element.backend_node_id, `
						position: absolute;
						top: -20px;
						left: 0;
						background-color: #4a90e2;
						color: white;
						padding: 2px 6px;
						font-size: 11px;
						font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
						font-weight: bold;
						border-radius: 3px;
						white-space: nowrap;
						z-index: ${{HIGHLIGHT_Z_INDEX + 1}};
						box-shadow: 0 2px 4px rgba(0,0,0,0.3);
						border: none;
						outline: none;
						margin: 0;
						line-height: 1.2;
					`);

					highlight.appendChild(label);
					container.appendChild(highlight);
				}});

				document.body.appendChild(container);

				console.log('Highlighting complete - added', interactiveElements.length, 'highlights');
				return {{ added: interactiveElements.length }};
			}})();
			"""

			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

			if result and 'result' in result and 'value' in result['result']:
				added_count = result['result']['value'].get('added', 0)
				self.logger.debug(f'Successfully added {added_count} highlight elements to browser DOM')
			else:
				self.logger.debug('Browser highlight injection completed')

		except Exception as e:
			self.logger.warning(f'Failed to add browser highlights: {e}')
			self.logger.debug(f'Browser highlight traceback: {traceback.format_exc()}')
