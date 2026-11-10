"""Browser Use's orange corner brackets around the element a click, focus or text input reached (port of Browser Use Pi
src/highlight.ts). Agent(highlight_actions=False) turns them off.

Cosmetic: drawn on a background thread, so no action waits for it; aria-hidden, in a closed shadow root and
pointer-transparent, so the accessibility tree, page text and clicks do not see it. One overlay at a time: a draw
removes the previous one, also in another frame or tab. A screenshot removes it first and holds back later draws until
it is captured: the model never sees a bracket. Every failure (detached node, navigation, CSP) is swallowed.
"""

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

TIMEOUT_S = 5.0

# Pi's drawCorners (geometry, color and timing of 0.x highlight_interaction_element), returning the overlay
DRAW_JS = """function () {
  const doc = this.ownerDocument;
  const rect = this.getBoundingClientRect();
  if (!this.isConnected || !rect.width || !rect.height) return;
  doc.querySelector('[data-browser-use-interaction-highlight]')?.remove();
  const host = doc.createElement('div');
  host.setAttribute('data-browser-use-interaction-highlight', 'true');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = `all:initial;position:absolute;left:${rect.left + doc.defaultView.scrollX}px;top:${rect.top + doc.defaultView.scrollY}px;width:${rect.width}px;height:${rect.height}px;pointer-events:none;z-index:2147483647;opacity:1;transition:opacity .3s;`;
  const root = host.attachShadow({ mode: 'closed' });
  const size = Math.max(8, Math.min(20, Math.min(rect.width, rect.height) * 0.35));
  for (const [vertical, horizontal] of [['top', 'left'], ['top', 'right'], ['bottom', 'left'], ['bottom', 'right']]) {
    const corner = doc.createElement('div');
    corner.style.cssText = `position:absolute;width:${size}px;height:${size}px;${vertical}:-10px;${horizontal}:-10px;border-${vertical}:3px solid rgb(255,127,39);border-${horizontal}:3px solid rgb(255,127,39);pointer-events:none;transition:all .15s ease-out;`;
    root.append(corner);
    setTimeout(() => {
      corner.style.setProperty(vertical, '-3px');
      corner.style.setProperty(horizontal, '-3px');
    }, 10);
  }
  doc.documentElement.append(host);
  setTimeout(() => {
    host.style.opacity = '0';
    setTimeout(() => host.remove(), 300);
  }, 1000);
  return host;
}"""


class Highlighter:
	"""after(method, session_id, params): call after each successful CDP call; draws for mouseReleased, DOM.focus and
	Input.insertText. hidden(): wrap a screenshot capture."""

	def __init__(self, cdp: Callable[..., Any], session: Callable[[], str | None], dialog: Callable[[], Any]):
		self.cdp = cdp  # raw cdp(method, session_id, **params): not counted, no dialog probe
		# the attached tab's session: an overlay is removed through its own tab's session, also after switch_tab()
		self.session = session
		self.dialog = dialog  # a JS dialog is open: the page answers no Runtime call until it is handled
		self.lock = threading.Lock()  # one draw or one capture at a time
		self.generation = 0  # a newer action supersedes a draw still resolving its node
		# (session, object group, overlay objectId): the one overlay that can be on a page
		self.shown: tuple[str | None, str, str] | None = None

	def after(self, method: str, session_id: str | None, params: dict) -> None:
		if not (
			(method == 'Input.dispatchMouseEvent' and params.get('type') == 'mouseReleased')
			or method in ('DOM.focus', 'Input.insertText')
		):
			return
		with self.lock:
			self.generation += 1
			generation = self.generation
		threading.Thread(target=self._draw, args=(generation, method, session_id, params), daemon=True).start()

	def _call(self, method: str, session_id: str | None, **params: Any) -> dict:
		return self.cdp(method, session_id, _response_timeout=TIMEOUT_S, **params)

	def _draw(self, generation: int, method: str, session_id: str | None, params: dict) -> None:
		group = f'browser-use-highlight-{generation}'
		done: tuple[str | None, str] | None = None  # this draw's objects, released at the end unless its overlay is shown
		try:
			session_id = session_id or self.session()
			done = (session_id, group)
			if method == 'Input.dispatchMouseEvent':
				hit = self._call('DOM.getNodeForLocation', session_id, x=round(params['x']), y=round(params['y']))
				node = {'backendNodeId': hit['backendNodeId']}
			elif method == 'DOM.focus':
				node = next({k: params[k]} for k in ('backendNodeId', 'nodeId', 'objectId') if k in params)
			else:
				r = self._call('Runtime.evaluate', session_id, expression='document.activeElement', objectGroup=group)
				node = {'objectId': r['result']['objectId']}
			if generation != self.generation:
				return
			if 'objectId' not in node:
				node = {'objectId': self._call('DOM.resolveNode', session_id, objectGroup=group, **node)['object']['objectId']}
			with self.lock:
				if generation != self.generation:
					return
				r = self._call(
					'Runtime.callFunctionOn',
					session_id,
					objectId=node['objectId'],
					functionDeclaration=DRAW_JS,
					objectGroup=group,
				)
				if host := r['result'].get('objectId'):  # kept until the next draw or screenshot
					# the draw replaced an overlay in its own document only, not one in an iframe or another tab
					if self.shown:
						self._remove(self.shown)
					self.shown, done = (session_id, group, host), None
		except Exception:  # detached nodes, navigation, CSP, an unsupported target: the action is not affected
			pass
		finally:
			if done:
				self._release(*done)

	def _release(self, session_id: str | None, group: str) -> None:
		with contextlib.suppress(Exception):
			self._call('Runtime.releaseObjectGroup', session_id, objectGroup=group)

	def _remove(self, shown: tuple[str | None, str, str]) -> None:
		with contextlib.suppress(Exception):
			self._call('Runtime.callFunctionOn', shown[0], objectId=shown[2], functionDeclaration='function () { this.remove() }')
		threading.Thread(target=self._release, args=shown[:2], daemon=True).start()  # a screenshot does not wait for it

	@contextlib.contextmanager
	def hidden(self) -> Iterator[None]:
		"""For a screenshot: remove the overlay still on screen; draws that finish meanwhile wait until after the capture."""
		with self.lock:
			# under a dialog the capture fails too; the overlay is removed before the next one
			if self.shown and not self.dialog():
				self._remove(self.shown)
				self.shown = None
			yield
