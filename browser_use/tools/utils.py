"""Utility functions for browser tools."""

import logging

from browser_use.dom.service import EnhancedDOMTreeNode

logger = logging.getLogger(__name__)


async def verify_checkbox_state_via_cdp(node: EnhancedDOMTreeNode, browser_session) -> bool | None:
	"""
	Verify checkbox state via CDP by querying the actual DOM element.

	Returns:
		True if checked, False if unchecked, None if couldn't verify
	"""
	try:
		# Try to get CDP session for the node
		cdp_session = await browser_session.cdp_client_for_node(node)

		# Resolve the node to get object ID
		result = await cdp_session.cdp_client.send.DOM.resolveNode(
			params={'backendNodeId': node.backend_node_id},
			session_id=cdp_session.session_id,
		)

		if 'object' not in result:
			return None

		object_id = result['object']['objectId']

		# For input[type=checkbox], check .checked property
		if node.tag_name == 'input' and node.attributes.get('type') == 'checkbox':
			check_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.checked; }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			return check_result.get('result', {}).get('value')

		# For role=checkbox, check aria-checked attribute
		elif node.attributes.get('role') == 'checkbox':
			attr_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.getAttribute("aria-checked"); }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			aria_checked = attr_result.get('result', {}).get('value')
			return aria_checked == 'true' if aria_checked else False

		return None
	except Exception as e:
		logger.debug(f'Failed to verify checkbox state via CDP: {e}')
		return None


def get_checkbox_state_description(node: EnhancedDOMTreeNode) -> str | None:
	"""Get the current checkbox state description (checked/unchecked or mixed)."""
	# For input[type=checkbox]
	if node.tag_name == 'input' and node.attributes.get('type') == 'checkbox':
		is_checked = node.attributes.get('checked', 'false').lower() in ['true', 'checked', '']
		# Also check AX node for more accurate state
		if node.ax_node and node.ax_node.properties:
			for prop in node.ax_node.properties:
				if prop.name == 'checked':
					is_checked = prop.value is True or prop.value == 'true'
					break
		return 'checked' if is_checked else 'unchecked'

	# For role=checkbox
	elif node.attributes.get('role') == 'checkbox':
		aria_checked = node.attributes.get('aria-checked', 'false').lower()
		if aria_checked == 'mixed':
			return 'mixed'
		return 'checked' if aria_checked == 'true' else 'unchecked'

	# For hidden checkbox in wrapper elements
	elif node.tag_name in ['label', 'span', 'div']:
		for child in node.children:
			if child.tag_name == 'input' and child.attributes.get('type') == 'checkbox':
				is_hidden = False
				if child.snapshot_node and child.snapshot_node.computed_styles:
					opacity = child.snapshot_node.computed_styles.get('opacity', '1')
					if opacity == '0' or opacity == '0.0':
						is_hidden = True

				if is_hidden or not child.is_visible:
					is_checked = child.attributes.get('checked', 'false').lower() in ['true', 'checked', '']
					if child.ax_node and child.ax_node.properties:
						for prop in child.ax_node.properties:
							if prop.name == 'checked':
								is_checked = prop.value is True or prop.value == 'true'
								break
					return 'checked' if is_checked else 'unchecked'

	return None


def get_click_description(node: EnhancedDOMTreeNode) -> str:
	"""Get a brief description of the clicked element for memory."""
	parts = []

	# Tag name
	parts.append(node.tag_name)

	# Add type for inputs
	if node.tag_name == 'input' and node.attributes.get('type'):
		input_type = node.attributes['type']
		parts.append(f'type={input_type}')

		# For checkboxes, include checked state
		if input_type == 'checkbox':
			is_checked = node.attributes.get('checked', 'false').lower() in ['true', 'checked', '']
			# Also check AX node
			if node.ax_node and node.ax_node.properties:
				for prop in node.ax_node.properties:
					if prop.name == 'checked':
						is_checked = prop.value is True or prop.value == 'true'
						break
			state = 'checked' if is_checked else 'unchecked'
			parts.append(f'checkbox-state={state}')

	# Add role if present
	if node.attributes.get('role'):
		role = node.attributes['role']
		parts.append(f'role={role}')

		# For role=checkbox, include state
		if role == 'checkbox':
			aria_checked = node.attributes.get('aria-checked', 'false').lower()
			is_checked = aria_checked in ['true', 'checked']
			if node.ax_node and node.ax_node.properties:
				for prop in node.ax_node.properties:
					if prop.name == 'checked':
						is_checked = prop.value is True or prop.value == 'true'
						break
			state = 'checked' if is_checked else 'unchecked'
			parts.append(f'checkbox-state={state}')

	# For labels/spans/divs, check if related to a hidden checkbox
	if node.tag_name in ['label', 'span', 'div'] and 'type=' not in ' '.join(parts):
		# Check children for hidden checkbox
		for child in node.children:
			if child.tag_name == 'input' and child.attributes.get('type') == 'checkbox':
				# Check if hidden
				is_hidden = False
				if child.snapshot_node and child.snapshot_node.computed_styles:
					opacity = child.snapshot_node.computed_styles.get('opacity', '1')
					if opacity == '0' or opacity == '0.0':
						is_hidden = True

				if is_hidden or not child.is_visible:
					# Get checkbox state
					is_checked = child.attributes.get('checked', 'false').lower() in ['true', 'checked', '']
					if child.ax_node and child.ax_node.properties:
						for prop in child.ax_node.properties:
							if prop.name == 'checked':
								is_checked = prop.value is True or prop.value == 'true'
								break
					state = 'checked' if is_checked else 'unchecked'
					parts.append(f'checkbox-state={state}')
					break

	# Add short text content if available
	text = node.get_all_children_text().strip()
	if text:
		short_text = text[:30] + ('...' if len(text) > 30 else '')
		parts.append(f'"{short_text}"')

	# Add key attributes like id, name, aria-label
	for attr in ['id', 'name', 'aria-label']:
		if node.attributes.get(attr):
			parts.append(f'{attr}={node.attributes[attr][:20]}')

	return ' '.join(parts)
