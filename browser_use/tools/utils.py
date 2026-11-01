"""Utility functions for browser tools."""

from typing import Any

from browser_use.dom.service import EnhancedDOMTreeNode

# CDP reports the same generic text ("Uncaught") for every JavaScript failure: the reason lives in
# `exception.description` and the position in `lineNumber`/`columnNumber`. Keep the formatted error
# short, since it ends up in the agent context.
_MAX_JS_EXCEPTION_CHARS = 1000
_TRUNCATED_SUFFIX = '... [truncated]'


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


def format_js_exception(exception_details: dict[str, Any] | None) -> str:
	"""Format a CDP ``Runtime.evaluate`` exception payload into a readable one-liner.

	Chromium puts the useful part of a JavaScript failure in ``exception.description``
	(``SyntaxError: Illegal return statement``), while ``text`` is usually only ``Uncaught``.
	Callers that read ``text`` alone therefore lose both the reason and the location.

	Args:
		exception_details: The ``exceptionDetails`` dict from a CDP evaluate response,
			or None/empty when the script did not throw.

	Returns:
		A one-line summary such as ``SyntaxError: Illegal return statement (line 1, col 1)``.
		Never raises: unknown or malformed payloads fall back to a generic message.
	"""
	if not isinstance(exception_details, dict) or not exception_details:
		return 'Unknown JavaScript error'

	text = str(exception_details.get('text') or '').strip()
	exception = exception_details.get('exception')
	if not isinstance(exception, dict):
		exception = {}

	summary = _describe_js_exception(exception)
	if not summary:
		return _truncate_js_exception(text or 'Unknown JavaScript error')

	# Some payloads repeat the generic "Uncaught" prefix inside the description.
	if text and text != summary and summary.startswith(text):
		summary = summary[len(text) :].lstrip(': ').strip() or text

	location = _js_exception_location(exception_details)
	message = f'{summary} ({location})' if location else summary
	return _truncate_js_exception(message)


def _describe_js_exception(exception: dict[str, Any]) -> str:
	"""Return the most specific one-line description available for a thrown value."""
	description = exception.get('description')
	if isinstance(description, str) and description.strip():
		# Runtime errors append a JS stack trace; the first line already names the error.
		return description.strip().splitlines()[0].strip()

	class_name = exception.get('className')
	if isinstance(class_name, str) and class_name.strip():
		return class_name.strip()

	if 'value' in exception:
		value = exception['value']
		kind = exception.get('type') or 'value'
		return f'{kind}: {value!r}' if isinstance(value, str) else f'{kind}: {value}'

	return ''


def _js_exception_location(exception_details: dict[str, Any]) -> str:
	"""Return a short `line X, col Y` (1-based) description of where the script failed."""
	line = exception_details.get('lineNumber')
	if _is_int(line):
		column = exception_details.get('columnNumber')
		if _is_int(column):
			return f'line {line + 1}, col {column + 1}'
		return f'line {line + 1}'

	stack_trace = exception_details.get('stackTrace')
	frames = stack_trace.get('callFrames') if isinstance(stack_trace, dict) else None
	for frame in frames or []:
		if not isinstance(frame, dict) or not _is_int(frame.get('lineNumber')):
			continue
		where = frame.get('url') or frame.get('functionName') or '<anonymous>'
		position = f'{frame["lineNumber"] + 1}'
		if _is_int(frame.get('columnNumber')):
			position += f':{frame["columnNumber"] + 1}'
		return f'at {where}:{position}'

	return ''


def _is_int(value: Any) -> bool:
	"""`isinstance` check that rejects booleans, which are ints in Python."""
	return isinstance(value, int) and not isinstance(value, bool)


def _truncate_js_exception(message: str) -> str:
	if len(message) <= _MAX_JS_EXCEPTION_CHARS:
		return message
	return message[: _MAX_JS_EXCEPTION_CHARS - len(_TRUNCATED_SUFFIX)].rstrip() + _TRUNCATED_SUFFIX
