"""Resolve native listboxes explicitly associated with a read-only picker input."""

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession


class ReadonlyDropdownTarget(BaseModel):
	"""Short-lived DOM object identities; never reuse a discovery result for a later action."""

	model_config = ConfigDict(extra='forbid', frozen=True)

	input_object_id: str
	select_object_id: str
	select_backend_node_id: int
	source: Literal['aria-controls', 'aria-owns', 'inline-opener']
	input_is_target: bool


class _RelationProbe(BaseModel):
	model_config = ConfigDict(extra='forbid')

	source: Literal['aria-controls', 'aria-owns', 'inline-opener'] | None = None
	input_is_target: bool = False
	error: str | None = None


_RESOLVE = r"""function() {
	const start = this;
	const root = start.getRootNode();
	const isListbox = element => element.tagName === 'SELECT' && !element.multiple && element.size > 1;
	const isReadonlyInput = element => element.tagName === 'INPUT' && element.readOnly &&
		['text', 'search', 'tel', 'url', 'email', 'number'].includes(element.type);
	const selects = start.tagName === 'SELECT' ? (isListbox(start) ? [start] : []) :
		Array.from((isReadonlyInput(start) ? root : start).querySelectorAll('select')).filter(isListbox);
	if (!selects.length) return null;
	const inputs = isReadonlyInput(start) ? [start] : Array.from(root.querySelectorAll('input[readonly]')).filter(isReadonlyInput);
	const idCounts = new Map();
	for (const element of root.querySelectorAll('[id]')) idCounts.set(element.id, (idCounts.get(element.id) || 0) + 1);
	function openerReferences(input, select) {
		// Treat comments and string literals as whole tokens: mentioning an ID in text is not a DOM reference.
		const tokens = ((input.getAttribute('onclick') || '').match(
			/\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|[^\s]/g
		) || []).filter(token => !token.startsWith('//') && !token.startsWith('/*'));
		const literal = (token, value) => token === JSON.stringify(value) || token === "'" + value + "'";
		const opens = index => tokens[index] === '.' &&
			((tokens[index + 1] === 'style' && ['.', '['].includes(tokens[index + 2])) ||
			 (tokens[index + 1] === 'focus' && tokens[index + 2] === '('));
		for (let index = 0; index < tokens.length; index++) {
			if (tokens[index] === select.id && /^[A-Za-z_$][\w$]*$/.test(select.id) && opens(index + 1)) return true;
			if (tokens[index] !== 'document' || tokens[index + 1] !== '.') continue;
			const method = tokens[index + 2];
			if (['getElementById', 'querySelector'].includes(method) && tokens[index + 3] === '(' &&
				literal(tokens[index + 4], method === 'getElementById' ? select.id : '#' + select.id) &&
				tokens[index + 5] === ')' && opens(index + 6) &&
				(method !== 'querySelector' || /^[A-Za-z_][\w-]*$/.test(select.id))) return true;
			if (method === 'all' && tokens[index + 3] === '[' && literal(tokens[index + 4], select.id) &&
				tokens[index + 5] === ']' && opens(index + 6)) return true;
		}
		return false;
	}
	function relation(input, select) {
		if (!select.id) return null;
		for (const attribute of ['aria-controls', 'aria-owns']) {
			if ((input.getAttribute(attribute) || '').split(/\s+/).includes(select.id)) return attribute;
		}
		// Legacy pickers commonly show/focus a named select in the input's inline click handler.
		// Recognize only explicit DOM access, never execute or try to interpret a business callback.
		if (openerReferences(input, select)) return 'inline-opener';
		return null;
	}
	const matches = [];
	for (const select of selects) for (const input of inputs) {
		const source = relation(input, select);
		if (source) {
			if (idCounts.get(select.id) !== 1) return {error: 'The associated listbox ID is duplicated. Use an unambiguous picker.'};
			matches.push({input, select, source, input_is_target: start === input});
		}
	}
	if (matches.length > 1) return {error: 'Several read-only inputs or listboxes are associated with this target. Use an unambiguous picker input.'};
	return matches[0] || null;
}"""


@contextlib.asynccontextmanager
async def resolve_readonly_dropdown(session: 'CDPSession', object_id: str) -> AsyncIterator[ReadonlyDropdownTarget | None]:
	"""Resolve declared DOM relationships without clicking, focusing, or inspecting nearby unrelated fields."""

	objects: list[str] = []
	try:
		response = await session.cdp_client.send.Runtime.callFunctionOn(
			params={'objectId': object_id, 'functionDeclaration': _RESOLVE}, session_id=session.session_id
		)
		if response.get('exceptionDetails'):
			raise ValueError('Could not inspect the dropdown relationship; refresh browser state.')
		relation_id = response['result'].get('objectId')
		if not relation_id:
			yield None
			return
		objects.append(relation_id)
		probe_response = await session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': relation_id,
				'functionDeclaration': 'function() { return {source: this.source, input_is_target: this.input_is_target, error: this.error}; }',
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		probe = _RelationProbe.model_validate(probe_response['result'].get('value'))
		if probe.error:
			raise ValueError(probe.error)
		assert probe.source is not None
		for property_name in ('input', 'select'):
			node_response = await session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': relation_id,
					'functionDeclaration': 'function(name) { return this[name]; }',
					'arguments': [{'value': property_name}],
				},
				session_id=session.session_id,
			)
			node_id = node_response['result'].get('objectId')
			if not node_id:
				raise ValueError('The dropdown relationship changed; refresh browser state.')
			objects.append(node_id)
		select_node = await session.cdp_client.send.DOM.describeNode(
			params={'objectId': objects[2]}, session_id=session.session_id
		)
		yield ReadonlyDropdownTarget(
			input_object_id=objects[1],
			select_object_id=objects[2],
			select_backend_node_id=select_node['node']['backendNodeId'],
			source=probe.source,
			input_is_target=probe.input_is_target,
		)
	finally:
		for remote_id in reversed(objects):
			with contextlib.suppress(Exception):
				await session.cdp_client.send.Runtime.releaseObject(params={'objectId': remote_id}, session_id=session.session_id)
