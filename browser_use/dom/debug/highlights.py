# Simple and fast highlighting - green boxes with numbers only

import json
import logging
import traceback

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMSelectorMap

logger = logging.getLogger(__name__)


async def remove_highlighting_script(dom_service: DomService) -> None:
	"""Remove all browser-use highlighting elements from the page."""
	try:
		# Get CDP client and session ID
		cdp_client = await dom_service.browser.get_cdp_client()
		session_id = await dom_service._get_current_page_session_id()

		logger.debug('🧹 Removing browser-use highlighting elements')

		# Simple removal script
		script = """
		(function() {
			const existingHighlights = document.querySelectorAll('[data-browser-use-highlight]');
			existingHighlights.forEach(el => el.remove());
		})();
		"""

		# Execute the removal script via CDP
		await cdp_client.send.Runtime.evaluate(params={'expression': script, 'returnByValue': True}, session_id=session_id)
		logger.debug('✅ All browser-use highlighting elements removed')

	except Exception as e:
		logger.debug(f'❌ Error removing highlighting elements: {e}')


async def inject_highlighting_script(dom_service: DomService, interactive_elements: DOMSelectorMap) -> None:
	"""Inject simple, fast highlighting script - just green boxes with numbers."""
	if not interactive_elements:
		logger.debug('⚠️ No interactive elements to highlight')
		return

	try:
		# Performance safeguard
		MAX_HIGHLIGHTS = 200
		total_elements = len(interactive_elements)

		if total_elements > MAX_HIGHLIGHTS:
			logger.debug(f'⚠️ Too many elements ({total_elements}) - limiting to first {MAX_HIGHLIGHTS} for performance')
			limited_elements = dict(list(interactive_elements.items())[:MAX_HIGHLIGHTS])
		else:
			limited_elements = interactive_elements

		# Get CDP client and session ID
		cdp_client = await dom_service.browser.get_cdp_client()
		session_id = await dom_service._get_current_page_session_id()

		logger.debug(f'📍 Creating simple highlighting for {len(limited_elements)} elements')

		# Remove any existing highlights first
		await remove_highlighting_script(dom_service)

		# Prepare minimal element data - just index and basic coords
		elements_data = []
		for interactive_index, node in limited_elements.items():
			# Get bounding box from snapshot_node if available
			if node.snapshot_node and node.snapshot_node.bounds:
				rect = node.snapshot_node.bounds
				elements_data.append(
					{'index': interactive_index, 'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height}
				)

		# Create simple, fast highlighting script
		script = f"""
		(function() {{
			const elementsData = {json.dumps(elements_data)};
			
			// Remove any existing highlights
			const existingHighlights = document.querySelectorAll('[data-browser-use-highlight]');
			existingHighlights.forEach(el => el.remove());
			
			// Create highlights - simple and fast
			elementsData.forEach(data => {{
				const highlight = document.createElement('div');
				highlight.setAttribute('data-browser-use-highlight', 'element');
				
				// Simple dark green box styling
				highlight.style.cssText = `
					position: absolute;
					left: ${{data.x}}px;
					top: ${{data.y}}px;
					width: ${{data.width}}px;
					height: ${{data.height}}px;
					outline: 2px solid #006400;
					background: transparent;
					pointer-events: none;
					z-index: 2147483647;
					box-sizing: border-box;
				`;
				
				// Simple number label
				const label = document.createElement('div');
				label.textContent = data.index;
				label.style.cssText = `
					position: absolute;
					top: -20px;
					left: 0px;
					background: #006400;
					color: white;
					padding: 2px 6px;
					font-size: 12px;
					font-family: monospace;
					font-weight: bold;
					border-radius: 3px;
					z-index: 2147483647;
					line-height: 1;
				`;
				
				highlight.appendChild(label);
				document.body.appendChild(highlight);
			}});
			
			console.log('✅ Simple highlighting complete:', elementsData.length, 'elements');
		}})();
		"""

		# Inject the simple script
		await cdp_client.send.Runtime.evaluate(params={'expression': script, 'returnByValue': True}, session_id=session_id)
		logger.debug(f'✅ Simple highlighting injected for {len(limited_elements)} elements')

	except Exception as e:
		logger.debug(f'❌ Error injecting highlighting script: {e}')
		traceback.print_exc()
