"""Explicit frame references over the existing CDP connection; no selected-frame state."""

import contextlib
import math
import time
import uuid
from contextlib import contextmanager

import browser_harness.helpers as helpers


def _deadline(timeout_s):
	if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
		raise ValueError('timeout_s must be a finite positive number')
	return time.monotonic() + timeout_s


def _call(deadline, method, session_id=None, **params):
	left = deadline - time.monotonic()
	if left <= 0:
		raise TimeoutError('Frame operation deadline exceeded; inspect state before retrying a mutation')
	return helpers.cdp(method, session_id=session_id, _response_timeout=left, **params)


def _tab(deadline):
	left = deadline - time.monotonic()
	if left <= 0:
		raise TimeoutError('Frame operation deadline exceeded')
	return helpers._send({'meta': 'current_tab'}, response_timeout=left)['targetId']


@contextmanager
def _attached(target_id, tab_id, deadline):
	sid = None
	try:
		if target_id != tab_id:
			sid = _call(deadline, 'Target.attachToTarget', targetId=target_id, flatten=True)['sessionId']
		yield sid
	finally:
		if sid:
			with contextlib.suppress(Exception):  # a navigation may already have removed it; never replace the original error
				helpers.cdp('Target.detachFromTarget', sessionId=sid, _response_timeout=0.25)


def _walk(tree):
	yield tree['frame']
	for child in tree.get('childFrames', []):
		yield from _walk(child)


def _frames(deadline):
	tab_id = _tab(deadline)
	frames = {}
	owners = {tab_id}

	def add(tree, target_id):
		for f in _walk(tree):
			frames[f['id']] = {
				'tab_id': tab_id,
				'target_id': target_id,
				'frame_id': f['id'],
				'loader_id': f['loaderId'],
				'parent_id': f.get('parentId'),
				'url': f['url'],
				'name': f.get('name', ''),
			}

	add(_call(deadline, 'Page.getFrameTree')['frameTree'], tab_id)
	pending = [t for t in _call(deadline, 'Target.getTargets')['targetInfos'] if t['type'] == 'iframe']
	while pending:
		advanced = False
		for target in pending[:]:
			# Current Chromium exposes ownership in TargetInfo. Older versions need the target's frame tree.
			if ('parentId' in target or 'parentFrameId' in target) and not (
				target.get('parentId') in owners or target.get('parentFrameId') in frames
			):
				continue
			with _attached(target['targetId'], tab_id, deadline) as sid:
				tree = _call(deadline, 'Page.getFrameTree', sid)['frameTree']
			if tree['frame'].get('parentId') in frames:
				add(tree, target['targetId'])
				owners.add(target['targetId'])
				pending.remove(target)
				advanced = True
		if not advanced:
			break
	if _tab(deadline) != tab_id:
		raise RuntimeError('Attached tab changed during frame discovery; call frame_list() again')
	return list(frames.values())


def frame_list(*, timeout_s=10):
	"""List this tab's main frame and descendants, including in-process children of iframe targets.

	References expire after navigation. A discovery error raises rather than reporting an empty frame list.
	This function neither switches tabs nor consumes the browser's event queue.
	"""
	return _frames(_deadline(timeout_s))


@contextmanager
def _document(frame, deadline):
	if not isinstance(frame, dict) or not all(
		isinstance(frame.get(k), str) for k in ('tab_id', 'target_id', 'frame_id', 'loader_id')
	):
		raise ValueError('Use a complete frame reference returned by frame_list()')
	if _tab(deadline) != frame['tab_id']:
		raise RuntimeError('Frame belongs to another tab; switch back or call frame_list() again')
	keys = ('tab_id', 'target_id', 'frame_id', 'loader_id')
	if not any(all(f[k] == frame[k] for k in keys) for f in _frames(deadline)):
		raise RuntimeError('Frame was removed or navigated; call frame_list() again. No expression was executed.')
	with _attached(frame['target_id'], frame['tab_id'], deadline) as sid:
		group = 'browser-use-frame-' + uuid.uuid4().hex
		try:
			tree = _call(deadline, 'Page.getFrameTree', sid)['frameTree']
			if not any(f['id'] == frame['frame_id'] and f['loaderId'] == frame['loader_id'] for f in _walk(tree)):
				raise RuntimeError('Frame changed during attachment; call frame_list() again')
			context = _call(deadline, 'Page.createIsolatedWorld', sid, frameId=frame['frame_id'], worldName='browser-use-frame')[
				'executionContextId'
			]
			isolated = _call(deadline, 'Runtime.evaluate', sid, expression='document', contextId=context, objectGroup=group)
			backend = _call(deadline, 'DOM.describeNode', sid, objectId=isolated['result']['objectId'])['node']['backendNodeId']
			# Omitting executionContextId resolves the document into its own main world, where app globals live.
			doc = _call(deadline, 'DOM.resolveNode', sid, backendNodeId=backend, objectGroup=group)['object']['objectId']
			yield sid, doc, group
		finally:
			with contextlib.suppress(Exception):
				helpers.cdp('Runtime.releaseObjectGroup', session_id=sid, objectGroup=group, _response_timeout=0.25)


def frame_eval(frame, expression, *, timeout_s=10):
	"""Evaluate one JavaScript expression in the frame's main world; use an IIFE for statements.

	Promises are awaited. Exceptions propagate; expressions are never retried or sent to the top page.
	"""
	if not isinstance(expression, str):
		raise TypeError('expression must be a JavaScript string')
	deadline = _deadline(timeout_s)
	with _document(frame, deadline) as (sid, doc, _):
		result = _call(
			deadline,
			'Runtime.callFunctionOn',
			sid,
			objectId=doc,
			functionDeclaration='function(source) { if (this !== document) throw new Error("Stale frame document"); return (0, eval)(source); }',
			arguments=[{'value': expression}],
			returnByValue=True,
			awaitPromise=True,
		)
		return helpers._runtime_value(result, expression)
