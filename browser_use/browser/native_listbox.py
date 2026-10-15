"""Select visible native single-select listboxes through one real pointer click."""

import contextlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from browser_use.browser.readonly_dropdown import ReadonlyDropdownTarget, resolve_readonly_dropdown

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession, CDPSession


class NativeListboxSelection(BaseModel):
	"""Evidence for a native option click; this does not verify application side effects."""

	method: Literal['native_listbox_click'] = 'native_listbox_click'
	success: bool = False
	click_dispatched: bool = False
	opener_click_dispatched: bool = False
	selection_verified: bool = False
	text: str | None = None
	value: str | None = None
	error: str | None = None
	picker_source: str | None = None
	readonly_input_value: str | None = None


class _DropdownOption(BaseModel):
	text: str
	value: str
	index: int
	selected: bool


class ReadonlyDropdownOptions(BaseModel):
	"""Discovery feedback for an associated picker; discovery does not click or change focus."""

	model_config = ConfigDict(extra='forbid')

	options: list[_DropdownOption]
	source: str
	selection_method: Literal['native_listbox_click'] = 'native_listbox_click'


class _PickerState(BaseModel):
	model_config = ConfigDict(extra='forbid')

	open: bool = False
	input_value: str = ''
	error: str | None = None


class _OptionProbe(BaseModel):
	applicable: bool
	index: int | None = None
	text: str | None = None
	value: str | None = None
	error: str | None = None


class _ClickPoint(BaseModel):
	x: float
	y: float


class _Viewport(BaseModel):
	x: float
	y: float
	width: float
	height: float


async def _point_in_root_viewport(
	browser: 'BrowserSession', session: 'CDPSession', point: _ClickPoint, allowed_nodes: set[int]
) -> _ClickPoint | None:
	"""Check each process boundary and map a target's viewport point to the page."""
	root_session = await browser.get_or_create_cdp_session(focus=False)
	while True:
		viewport_response = await session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': '({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight})',
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		viewport = _Viewport.model_validate(viewport_response['result'].get('value'))
		if not (0 <= point.x < viewport.width and 0 <= point.y < viewport.height):
			return None
		# DOM hit testing uses document coordinates; CDP mouse input uses viewport coordinates.
		hit = await session.cdp_client.send.DOM.getNodeForLocation(
			params={'x': round(point.x + viewport.x), 'y': round(point.y + viewport.y)}, session_id=session.session_id
		)
		if hit.get('backendNodeId') not in allowed_nodes:
			return None
		if session.session_id == root_session.session_id:
			return point
		# A remote iframe's quads are local to its target. Its owner quad is in the parent target.
		tree = await session.cdp_client.send.Page.getFrameTree(session_id=session.session_id)
		frame = tree['frameTree']['frame']
		parent_id = frame.get('parentId')
		if not parent_id:
			return None
		parent_session = await browser.cdp_client_for_frame(parent_id)
		owner = await parent_session.cdp_client.send.DOM.getFrameOwner(
			params={'frameId': frame['id']}, session_id=parent_session.session_id
		)
		box = await parent_session.cdp_client.send.DOM.getBoxModel(
			params={'backendNodeId': owner['backendNodeId']}, session_id=parent_session.session_id
		)
		quad = box['model']['content']
		u, v = point.x / viewport.width, point.y / viewport.height
		point = _ClickPoint(
			x=quad[0] + u * (quad[2] - quad[0]) + v * (quad[6] - quad[0]),
			y=quad[1] + u * (quad[3] - quad[1]) + v * (quad[7] - quad[1]),
		)
		allowed_nodes = {owner['backendNodeId']}
		session = parent_session


_PROBE = """function(targetText) {
	if (this.tagName !== 'SELECT' || this.multiple || this.size <= 1) return {applicable: false};
	const fail = error => ({applicable: true, error});
	if (!this.isConnected) return fail('The listbox is detached; refresh browser state.');
	if (this.matches(':disabled') || this.closest('[inert]')) return fail('The listbox is disabled or inert.');
	const matches = Array.from(this.options).filter(option =>
		option.text.trim().toLowerCase() === targetText.toLowerCase() ||
		option.value.toLowerCase() === targetText.toLowerCase());
	if (!matches.length) return fail('No listbox option matches the requested text or value.');
	if (matches.length !== 1) return fail('Several listbox options match; use a unique option text or value.');
	const option = matches[0];
	if (option.matches(':disabled')) return fail('The requested option is disabled.');
	for (let node = option; node; node = node.parentElement) {
		const style = node.ownerDocument.defaultView.getComputedStyle(node);
		if (node.hidden || style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) === 0)
			return fail('The listbox or requested option is hidden; open the listbox first.');
	}
	return {applicable: true, index: option.index, text: option.text.trim(), value: option.value};
}"""

_SETTLE = """async function() {
	// Scrolling can update layout before the compositor's hit-test data. Wait for both.
	await new Promise(resolve => {
		const win = this.ownerDocument.defaultView;
		const timer = win.setTimeout(resolve, 100);
		win.requestAnimationFrame(() => win.requestAnimationFrame(() => {
			win.clearTimeout(timer); resolve();
		}));
	});
}"""


async def _picker_state(session: 'CDPSession', picker: ReadonlyDropdownTarget) -> _PickerState:
	response = await session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': picker.select_object_id,
			'functionDeclaration': """function(input) {
				if (!this.isConnected || !input.isConnected || !input.readOnly)
					return {error: 'The read-only picker changed; refresh browser state.'};
				if (input.matches(':disabled') || input.closest('[inert]'))
					return {error: 'The read-only picker input is disabled or inert.'};
				let visible = this.getClientRects().length > 0;
				for (let node = this; node; node = node.parentElement) {
					const style = node.ownerDocument.defaultView.getComputedStyle(node);
					visible &&= !node.hidden && style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) !== 0;
				}
				return {open: visible, input_value: input.value};
			}""",
			'arguments': [{'objectId': picker.input_object_id}],
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	if response.get('exceptionDetails'):
		raise ValueError('Could not inspect the read-only picker state.')
	return _PickerState.model_validate(response['result'].get('value'))


async def _click_point(
	browser: 'BrowserSession', session: 'CDPSession', object_id: str, additional_allowed_nodes: set[int] | None = None
) -> _ClickPoint:
	"""Scroll one retained node into view and require unobstructed hits through every frame."""
	await session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': object_id,
			'functionDeclaration': "function() { this.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'}); }",
		},
		session_id=session.session_id,
	)
	await session.cdp_client.send.Runtime.callFunctionOn(
		params={'objectId': object_id, 'functionDeclaration': _SETTLE, 'awaitPromise': True}, session_id=session.session_id
	)
	quads = await session.cdp_client.send.DOM.getContentQuads(params={'objectId': object_id}, session_id=session.session_id)
	node = await session.cdp_client.send.DOM.describeNode(params={'objectId': object_id}, session_id=session.session_id)
	allowed_nodes = {node['node']['backendNodeId']} | (additional_allowed_nodes or set())
	for quad in quads.get('quads', []):
		if len(quad) != 8 or max(quad[0::2]) - min(quad[0::2]) < 1 or max(quad[1::2]) - min(quad[1::2]) < 1:
			continue
		candidate = _ClickPoint(x=sum(quad[0::2]) / 4, y=sum(quad[1::2]) / 4)
		point = await _point_in_root_viewport(browser, session, candidate, allowed_nodes)
		if point is not None:
			return point
	raise ValueError('The target is not visible at a clickable point or is covered by another element.')


async def _dispatch_click(session: 'CDPSession', point: _ClickPoint) -> None:
	"""Dispatch one pointer click; never retry a press whose delivery is uncertain."""
	try:
		await session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mousePressed', 'x': point.x, 'y': point.y, 'button': 'left', 'clickCount': 1},
			session_id=session.session_id,
		)
	finally:
		await session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseReleased', 'x': point.x, 'y': point.y, 'button': 'left', 'clickCount': 1},
			session_id=session.session_id,
		)


async def get_readonly_dropdown_options(session: 'CDPSession', object_id: str) -> ReadonlyDropdownOptions | None:
	"""Discover click selection from a live read-only input/listbox association."""
	async with resolve_readonly_dropdown(session, object_id) as picker:
		if picker is None:
			return None
		response = await session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': picker.select_object_id,
				'functionDeclaration': """function() { return Array.from(this.options, option => ({
					text: option.text.trim(), value: option.value, index: option.index, selected: option.selected
				})); }""",
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		if response.get('exceptionDetails'):
			raise ValueError('Could not read the associated listbox options.')
		return ReadonlyDropdownOptions.model_validate({'options': response['result'].get('value'), 'source': picker.source})


async def select_native_listbox(
	browser: 'BrowserSession', session: 'CDPSession', object_id: str, text: str
) -> NativeListboxSelection | None:
	"""Recheck picker ownership immediately before selecting; ordinary selects retain their original path."""
	opener_click_dispatched = False
	try:
		async with resolve_readonly_dropdown(session, object_id) as picker:
			if picker is None:
				return None
			state = await _picker_state(session, picker)
			if state.error:
				return NativeListboxSelection(error=state.error, picker_source=picker.source)
			if not state.open:
				point = await _click_point(browser, session, picker.input_object_id)
				input_session = await browser.get_or_create_cdp_session(focus=False)
				await input_session.cdp_client.send.Input.dispatchMouseEvent(
					params={'type': 'mouseMoved', 'x': point.x, 'y': point.y}, session_id=input_session.session_id
				)
				opener_click_dispatched = True
				await _dispatch_click(input_session, point)
				await session.cdp_client.send.Runtime.callFunctionOn(
					params={'objectId': picker.input_object_id, 'functionDeclaration': _SETTLE, 'awaitPromise': True},
					session_id=session.session_id,
				)
				state = await _picker_state(session, picker)
				if state.error or not state.open:
					return NativeListboxSelection(
						error=state.error
						or 'The picker input was clicked but its associated listbox did not open. Inspect the page.',
						picker_source=picker.source,
						opener_click_dispatched=True,
					)
			result = await _select_bound_listbox(browser, session, picker.select_backend_node_id, picker.select_object_id, text)
			result.picker_source = picker.source
			result.opener_click_dispatched = opener_click_dispatched
			if result.success:
				# A failed auxiliary readback must retain the already-dispatched click's outcome.
				with contextlib.suppress(Exception):
					state = await _picker_state(session, picker)
					if not state.error:
						result.readonly_input_value = state.input_value
			return result
	except Exception as error:
		return NativeListboxSelection(
			error=f'Could not use the read-only picker: {error}. Inspect the page before retrying.',
			opener_click_dispatched=opener_click_dispatched,
		)


async def _select_bound_listbox(
	browser: 'BrowserSession', session: 'CDPSession', select_backend_node_id: int, select_id: str, text: str
) -> NativeListboxSelection:
	"""Click one option in a verified read-only picker's native listbox.

	Never pre-set the selection, synthesize DOM events, or retry a dispatched click:
	legacy pages can commit data in onclick and hide the listbox in onblur.
	"""
	probe_response = await session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': select_id,
			'functionDeclaration': _PROBE,
			'arguments': [{'value': text}],
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	if probe_response.get('exceptionDetails'):
		raise ValueError('Could not inspect the dropdown; refresh browser state.')
	probe = _OptionProbe.model_validate(probe_response['result'].get('value'))
	if not probe.applicable:
		return NativeListboxSelection(error='The associated control is no longer a native single-select listbox.')
	result = NativeListboxSelection(text=probe.text, value=probe.value, error=probe.error)
	if probe.error:
		return result

	option_id: str | None = None
	try:
		option_response = await session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': select_id,
				'functionDeclaration': 'function(index) { return this.options[index]; }',
				'arguments': [{'value': probe.index}],
			},
			session_id=session.session_id,
		)
		option_id = option_response['result'].get('objectId')
		if not option_id:
			raise ValueError('The requested option is no longer available.')
		point = await _click_point(browser, session, option_id, {select_backend_node_id})
		input_session = await browser.get_or_create_cdp_session(focus=False)
		# Keep the original option object: do not accidentally select a replacement after scrolling.
		ready = await session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': select_id,
				'functionDeclaration': """function(option, value) {
					return this.isConnected && option.isConnected && option.closest('select') === this &&
						option.value === value && !this.matches(':disabled') && !option.matches(':disabled');
				}""",
				'arguments': [{'objectId': option_id}, {'value': probe.value}],
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		if ready['result'].get('value') is not True:
			raise ValueError('The listbox changed before the click; refresh browser state.')
		await input_session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': point.x, 'y': point.y}, session_id=input_session.session_id
		)
		result.click_dispatched = True
		await _dispatch_click(input_session, point)
		await session.cdp_client.send.Runtime.callFunctionOn(
			params={'objectId': select_id, 'functionDeclaration': _SETTLE, 'awaitPromise': True},
			session_id=session.session_id,
		)
		verified = await session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': select_id,
				'functionDeclaration': """function(option, value) {
					return this.isConnected && option.isConnected && option.closest('select') === this &&
						option.selected && option.value === value && this.value === value;
				}""",
				'arguments': [{'objectId': option_id}, {'value': probe.value}],
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		result.selection_verified = verified['result'].get('value') is True
		result.success = result.selection_verified
		if not result.success:
			result.error = 'The option was clicked, but its selection could not be verified. Inspect the page before retrying.'
	except Exception as exc:
		if result.click_dispatched:
			result.error = (
				'A listbox click was attempted, but its result could not be verified. Inspect the page before retrying.'
			)
		else:
			result.error = f'Could not click the native listbox option: {exc}'
	finally:
		if option_id:
			with contextlib.suppress(Exception):
				await session.cdp_client.send.Runtime.releaseObject(params={'objectId': option_id}, session_id=session.session_id)
	return result
