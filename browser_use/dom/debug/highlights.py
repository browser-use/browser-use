# 100% vibe coded

import json
import traceback

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMSelectorMap


def analyze_element_interactivity(element: dict) -> dict:
	"""Analyze why an element is considered interactive and assign confidence level."""
	element_type = element['element_name'].lower()
	attributes = element.get('attributes', {})

	# Default reasoning structure
	reasoning = {'confidence': 'LOW', 'primary_reason': 'unknown', 'element_type': element_type, 'reasons': []}

	# High confidence elements
	if element_type in ['button', 'a', 'input', 'select', 'textarea']:
		reasoning['confidence'] = 'HIGH'
		reasoning['primary_reason'] = 'semantic_element'
		reasoning['reasons'].append(f'Semantic interactive element: {element_type}')

	# Check for interactive attributes
	interactive_attrs = ['onclick', 'onchange', 'href', 'type', 'role']
	found_attrs = [attr for attr in interactive_attrs if attr in attributes]
	if found_attrs:
		if reasoning['confidence'] != 'HIGH':
			reasoning['confidence'] = 'HIGH' if element_type in ['button', 'a'] else 'MEDIUM'
		reasoning['primary_reason'] = 'interactive_attributes'
		reasoning['reasons'].append(f'Interactive attributes: {", ".join(found_attrs)}')

	# Check for ARIA roles
	role = attributes.get('role', '').lower()
	if role in ['button', 'link', 'checkbox', 'radio', 'menuitem', 'tab']:
		reasoning['confidence'] = 'HIGH'
		reasoning['primary_reason'] = 'aria_role'
		reasoning['reasons'].append(f'Interactive ARIA role: {role}')

	# Check if marked as clickable from snapshot
	if element.get('is_clickable'):
		if reasoning['confidence'] == 'LOW':
			reasoning['confidence'] = 'MEDIUM'
		reasoning['reasons'].append('Marked as clickable in DOM snapshot')

	# Check for valid bounding box
	if element.get('width', 0) > 0 and element.get('height', 0) > 0:
		reasoning['reasons'].append(f'Valid bounding box: {element["width"]}x{element["height"]}')
	else:
		reasoning['confidence'] = 'LOW'
		reasoning['reasons'].append('Invalid or missing bounding box')

	# Fallback reasoning
	if not reasoning['reasons']:
		reasoning['reasons'].append('Element found in selector map')
		reasoning['primary_reason'] = 'selector_mapped'

	return reasoning


def convert_dom_selector_map_to_highlight_format(selector_map: DOMSelectorMap) -> list[dict]:
	"""Convert DOMSelectorMap to the format expected by the highlighting script."""
	elements = []

	for interactive_index, node in selector_map.items():
		# Get bounding box from snapshot_node if available (adapted from working implementation)
		bbox = None
		if node.snapshot_node:
			# Try bounds first, then clientRects
			rect = node.snapshot_node.bounds
			if rect:
				bbox = {'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height}

		# Only include elements with valid bounding boxes (following working implementation)
		if bbox and bbox.get('width', 0) > 0 and bbox.get('height', 0) > 0:
			element = {
				'x': bbox['x'],
				'y': bbox['y'],
				'width': bbox['width'],
				'height': bbox['height'],
				'interactive_index': interactive_index,
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

			# Analyze why this element is interactive
			reasoning = analyze_element_interactivity(element)
			element['reasoning'] = reasoning

			elements.append(element)
		else:
			# Skip elements without valid bounding boxes for now
			# Could add fallback positioning here if needed
			pass

	return elements


async def remove_highlighting_script(dom_service: DomService) -> None:
	"""Remove all browser-use highlighting elements from the page."""
	try:
		# Get CDP client and session ID
		cdp_client = await dom_service._get_cdp_client()
		session_id = await dom_service._get_current_page_session_id()

		print('🧹 Removing browser-use highlighting elements')

		# Create script to remove all highlights
		script = """
		(function() {
			// Remove any existing highlights
			const existingHighlights = document.querySelectorAll('[data-browser-use-highlight]');
			console.log('Removing', existingHighlights.length, 'browser-use highlight elements');
			existingHighlights.forEach(el => el.remove());
		})();
		"""

		# Execute the removal script via CDP
		await cdp_client.send.Runtime.evaluate(params={'expression': script, 'returnByValue': True}, session_id=session_id)
		print('✅ All browser-use highlighting elements removed')

	except Exception as e:
		print(f'❌ Error removing highlighting elements: {e}')
		traceback.print_exc()


async def inject_highlighting_script(dom_service: DomService, interactive_elements: DOMSelectorMap) -> None:
	"""Inject JavaScript to highlight interactive elements with detailed hover tooltips that work around CSP restrictions."""
	if not interactive_elements:
		print('⚠️ No interactive elements to highlight')
		return

	try:
		# Convert DOMSelectorMap to the format expected by the JavaScript
		converted_elements = convert_dom_selector_map_to_highlight_format(interactive_elements)

		# Get CDP client and session ID
		cdp_client = await dom_service._get_cdp_client()
		session_id = await dom_service._get_current_page_session_id()

		print(f'📍 Creating CSP-safe highlighting for {len(converted_elements)} elements')

		# Remove any existing highlights first
		await remove_highlighting_script(dom_service)

		# Create CSP-safe highlighting script using DOM methods instead of innerHTML
		# Uses outline-only highlights with reasonable z-index to avoid blocking page content
		script = f"""
		(function() {{
			// Interactive elements data with reasoning
			const interactiveElements = {json.dumps(converted_elements)};
			
			console.log('=== BROWSER-USE HIGHLIGHTING ===');
			console.log('Highlighting', interactiveElements.length, 'interactive elements');
			
			// Use a high but reasonable z-index to be visible without covering important content
			// High enough for most content but not maximum to avoid blocking critical popups/modals
			const HIGHLIGHT_Z_INDEX = 999999; // High but reasonable z-index
			
			// Create container for all highlights - use absolute positioning to cover entire document
			const container = document.createElement('div');
			container.id = 'browser-use-debug-highlights';
			container.setAttribute('data-browser-use-highlight', 'container');
			
			// Get document dimensions to ensure container covers entire scrollable area
			const docHeight = Math.max(
				document.body.scrollHeight,
				document.body.offsetHeight,
				document.documentElement.clientHeight,
				document.documentElement.scrollHeight,
				document.documentElement.offsetHeight
			);
			const docWidth = Math.max(
				document.body.scrollWidth,
				document.body.offsetWidth,
				document.documentElement.clientWidth,
				document.documentElement.scrollWidth,
				document.documentElement.offsetWidth
			);
			
			container.style.cssText = `
				position: absolute;
				top: 0;
				left: 0;
				width: ${{docWidth}}px;
				height: ${{docHeight}}px;
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
			
			// Helper function to create text nodes safely (CSP-friendly)
			function createTextElement(tag, text, styles) {{
				const element = document.createElement(tag);
				element.textContent = text;
				if (styles) element.style.cssText = styles;
				return element;
			}}
			
			// Add enhanced highlights with detailed tooltips
			interactiveElements.forEach((element, index) => {{
				const highlight = document.createElement('div');
				highlight.setAttribute('data-browser-use-highlight', 'element');
				highlight.setAttribute('data-element-id', element.interactive_index);
				highlight.style.cssText = `
					position: absolute;
					left: ${{element.x}}px;
					top: ${{element.y}}px;
					width: ${{element.width}}px;
					height: ${{element.height}}px;
					outline: 2px solid #4a90e2;
					outline-offset: -2px;
					background: transparent;
					pointer-events: none;
					box-sizing: content-box;
					transition: outline 0.2s ease;
					margin: 0;
					padding: 0;
					border: none;
				`;
				
				// Enhanced label with interactive index
				const label = createTextElement('div', element.interactive_index, `
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
				
				// Enhanced tooltip with detailed reasoning (CSP-safe)
				const tooltip = document.createElement('div');
				tooltip.setAttribute('data-browser-use-highlight', 'tooltip');
				tooltip.style.cssText = `
					position: absolute;
					top: -160px;
					left: 50%;
					transform: translateX(-50%);
					background-color: rgba(0, 0, 0, 0.95);
					color: white;
					padding: 12px 16px;
					font-size: 12px;
					font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
					border-radius: 8px;
					white-space: nowrap;
					z-index: ${{HIGHLIGHT_Z_INDEX + 2}};
					opacity: 0;
					visibility: hidden;
					transition: all 0.3s ease;
					box-shadow: 0 6px 20px rgba(0,0,0,0.5);
					border: 1px solid #666;
					max-width: 400px;
					white-space: normal;
					line-height: 1.4;
					min-width: 200px;
					margin: 0;
				`;
				
				// Build detailed tooltip content with reasoning (CSP-safe DOM creation)
				const reasoning = element.reasoning || {{}};
				const confidence = reasoning.confidence || 'UNKNOWN';
				const primaryReason = reasoning.primary_reason || 'unknown';
				const reasons = reasoning.reasons || [];
				const elementType = reasoning.element_type || element.element_name || 'UNKNOWN';
				
				// Determine confidence color and styling
				let confidenceColor = '#4a90e2';
				let confidenceIcon = '🔍';
				let outlineColor = '#4a90e2';
				let shadowColor = '#4a90e2';
				
				if (confidence === 'HIGH') {{
					confidenceColor = '#28a745';
					confidenceIcon = '✅';
					outlineColor = '#28a745';
					shadowColor = '#28a745';
				}} else if (confidence === 'MEDIUM') {{
					confidenceColor = '#ffc107';
					confidenceIcon = '⚠️';
					outlineColor = '#ffc107';
					shadowColor = '#ffc107';
				}} else {{
					confidenceColor = '#fd7e14';
					confidenceIcon = '❓';
					outlineColor = '#fd7e14';
					shadowColor = '#fd7e14';
				}}
				
				// Create tooltip header
				const header = createTextElement('div', `${{confidenceIcon}} [${{element.interactive_index}}] ${{elementType.toUpperCase()}}`, `
					color: ${{confidenceColor}};
					font-weight: bold;
					font-size: 13px;
					margin-bottom: 8px;
					border-bottom: 1px solid #666;
					padding-bottom: 4px;
				`);
				
				// Create confidence indicator
				const confidenceDiv = createTextElement('div', `${{confidence}} CONFIDENCE`, `
					color: ${{confidenceColor}};
					font-size: 11px;
					font-weight: bold;
					margin-bottom: 8px;
				`);
				
				// Create primary reason
				const primaryReasonDiv = createTextElement('div', `Primary: ${{primaryReason.replace('_', ' ').toUpperCase()}}`, `
					color: #fff;
					font-size: 11px;
					margin-bottom: 6px;
					font-weight: bold;
				`);
				
				// Create reasons list
				const reasonsContainer = document.createElement('div');
				reasonsContainer.style.cssText = `
					font-size: 10px;
					color: #ccc;
					margin-top: 4px;
				`;
				
				if (reasons.length > 0) {{
					const reasonsTitle = createTextElement('div', 'Evidence:', `
						color: #fff;
						font-size: 10px;
						margin-bottom: 4px;
						font-weight: bold;
					`);
					reasonsContainer.appendChild(reasonsTitle);
					
					reasons.slice(0, 4).forEach(reason => {{
						const reasonDiv = createTextElement('div', `• ${{reason}}`, `
							color: #ccc;
							font-size: 10px;
							margin-bottom: 2px;
							padding-left: 4px;
						`);
						reasonsContainer.appendChild(reasonDiv);
					}});
					
					if (reasons.length > 4) {{
						const moreDiv = createTextElement('div', `... and ${{reasons.length - 4}} more`, `
							color: #999;
							font-size: 9px;
							font-style: italic;
							margin-top: 2px;
						`);
						reasonsContainer.appendChild(moreDiv);
					}}
				}} else {{
					const noReasonsDiv = createTextElement('div', 'No specific evidence found', `
						color: #999;
						font-size: 10px;
						font-style: italic;
					`);
					reasonsContainer.appendChild(noReasonsDiv);
				}}
				
				// Add bounding box info
				const boundsDiv = createTextElement('div', `Position: (${{Math.round(element.x)}}, ${{Math.round(element.y)}}) Size: ${{Math.round(element.width)}}×${{Math.round(element.height)}}`, `
					color: #888;
					font-size: 9px;
					margin-top: 8px;
					border-top: 1px solid #444;
					padding-top: 4px;
				`);
				
				// Assemble tooltip
				tooltip.appendChild(header);
				tooltip.appendChild(confidenceDiv);
				tooltip.appendChild(primaryReasonDiv);
				tooltip.appendChild(reasonsContainer);
				tooltip.appendChild(boundsDiv);
				
				// Set highlight colors based on confidence (outline only)
				highlight.style.outline = `2px solid ${{outlineColor}}`;
				label.style.backgroundColor = outlineColor;
				
				// Add subtle hover effects (outline only, no background)
				highlight.addEventListener('mouseenter', () => {{
					highlight.style.outline = '3px solid #ff6b6b';
					highlight.style.outlineOffset = '-1px';
					tooltip.style.opacity = '1';
					tooltip.style.visibility = 'visible';
					label.style.backgroundColor = '#ff6b6b';
					label.style.transform = 'scale(1.1)';
				}});
				
				highlight.addEventListener('mouseleave', () => {{
					highlight.style.outline = `2px solid ${{outlineColor}}`;
					highlight.style.outlineOffset = '-2px';
					tooltip.style.opacity = '0';
					tooltip.style.visibility = 'hidden';
					label.style.backgroundColor = outlineColor;
					label.style.transform = 'scale(1)';
				}});
				
				highlight.appendChild(tooltip);
				highlight.appendChild(label);
				container.appendChild(highlight);
			}});
			
			// Add container to document
			document.body.appendChild(container);
			
			console.log('✅ Browser-use highlighting complete');
		}})();
		"""

		# Inject the enhanced CSP-safe script via CDP
		await cdp_client.send.Runtime.evaluate(params={'expression': script, 'returnByValue': True}, session_id=session_id)
		print(f'✅ Enhanced CSP-safe highlighting injected for {len(converted_elements)} elements')

	except Exception as e:
		print(f'❌ Error injecting enhanced highlighting script: {e}')
		traceback.print_exc()
