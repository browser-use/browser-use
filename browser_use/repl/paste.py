"""Bounded transport for one synthetic editor paste; never a persistence acknowledgement."""

import browser_harness.helpers as helpers

from browser_use.repl.frames import _call, _deadline, _document, _frames

# At worst, one Unicode code point takes 12 bytes in JSON (a surrogate pair).
_CHUNK_CHARS = 4096
_MAX_BYTES = 1024 * 1024
_PASTE = """function() {
    if (this.document !== document) throw new Error('Stale frame document');
    const reject = reason => ({status:'not_dispatched', reason, input_verified:false, persistence_verified:false});
    if (this.reason) return reject(this.reason);
    const target = this.target;
    if (!target.isConnected || target.ownerDocument !== document || target.disabled || target.readOnly || target.getAttribute('aria-disabled') === 'true')
        return reject('Target is detached, disabled or read-only');
    target.focus();
    if (document.activeElement !== target) return reject('Target could not receive focus');
    const data = new DataTransfer();
    data.setData('text/plain', this.text);
    if (this.html !== null) data.setData('text/html', this.html);
    const event = new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true, composed:true});
    target.dispatchEvent(event);
    return {status:'dispatched', default_prevented:event.defaultPrevented,
            input_verified:false, persistence_verified:false};
}"""


def dispatch_paste(selector, text, *, frame=None, html=None, timeout_s=10):
	"""Send one synthetic paste to an observed editor handler, with chunked transport below the IPC limit.

	No system clipboard, selection changes, fallback or replay. A dispatched event does not prove insertion.
	A timeout after sending the event is outcome_unknown: read the editor before another mutation.
	"""
	if not isinstance(selector, str) or not selector.strip():
		raise ValueError('selector must be a nonempty CSS selector')
	if not isinstance(text, str) or (html is not None and not isinstance(html, str)):
		raise TypeError('text must be a string; html must be a string or None')
	if len(text.encode('utf-8')) + len((html or '').encode('utf-8')) > _MAX_BYTES:
		raise ValueError('Paste payload exceeds 1 MiB; use an observed import interface or smaller batches')
	if len(selector.encode('utf-8')) > 4096:
		raise ValueError('selector exceeds 4096 bytes')
	deadline = _deadline(timeout_s)
	possibly_sent = False
	try:
		if frame is None:
			frame = _frames(deadline)[0]
		with _document(frame, deadline) as (sid, doc, group):
			response = _call(
				deadline,
				'Runtime.callFunctionOn',
				sid,
				objectId=doc,
				objectGroup=group,
				functionDeclaration="""function(selector, hasHtml) {
                    if (this !== document) throw new Error("Stale frame document");
                    const matches = document.querySelectorAll(selector);
                    return {document:this, target:matches.length === 1 ? matches[0] : null,
                            reason:matches.length === 1 ? null : 'Selector must match exactly one element; matched ' + matches.length,
                            text:"", html:hasHtml ? "" : null};
                }""",
				arguments=[{'value': selector}, {'value': html is not None}],
			)
			helpers._runtime_value(response, 'initialize paste transfer')
			holder = response['result']['objectId']
			for name, value in (('text', text), ('html', html or '')):
				for offset in range(0, len(value), _CHUNK_CHARS):
					result = _call(
						deadline,
						'Runtime.callFunctionOn',
						sid,
						objectId=holder,
						functionDeclaration='function(name, chunk) { this[name] += chunk; }',
						arguments=[{'value': name}, {'value': value[offset : offset + _CHUNK_CHARS]}],
						returnByValue=True,
					)
					helpers._runtime_value(result, 'transfer paste chunk')
			possibly_sent = True
			result = _call(
				deadline,
				'Runtime.callFunctionOn',
				sid,
				objectId=holder,
				functionDeclaration=_PASTE,
				returnByValue=True,
			)
			return helpers._runtime_value(result, 'dispatch editor paste')
	except Exception as exc:
		status = 'outcome_unknown' if possibly_sent else 'not_dispatched'
		raise RuntimeError(
			f'Paste {status}: {exc}. Inspect editor state before retrying; no automatic replay was performed.'
		) from exc
