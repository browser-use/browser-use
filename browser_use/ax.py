"""Ultrafast mode: Browser Use Pi's src/ax.ts in Python (bu.state(), bu.click(id), bu.type(id, text)).

Same names, defaults, waits and printed text as Pi. Differences forced by Python + browser-harness:
synchronous helpers (no await), keyword options (enter=True, max=30000), and CDP events read from the
browser-harness daemon's buffer by a background thread instead of an event tap. That buffer is shared by every
client of one daemon (BU_NAME), so give each ultrafast agent its own daemon: another agent or browser-harness CLI
on it would miss the dialogs and network events bu reads. Clicks send no mouseMoved (see _click_at): mouseover,
mouseenter and :hover still fire on press, mousemove handlers do not.
"""

# pyright: reportArgumentType=false, reportCallIssue=false, reportOptionalMemberAccess=false
# (verbatim port of Pi ax.ts: CDP params are untyped dicts)
from __future__ import annotations

import ast
import json
import math
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

CONTROLS = set(
	'button link textbox searchbox combobox listbox option checkbox radio switch slider spinbutton tab menuitem '
	'menuitemcheckbox menuitemradio treeitem'.split(' ')
)
OVERLAYS = {'dialog', 'alertdialog', 'menu', 'listbox', 'option'}
# Text inside these is one line; text across them is not joined.
BLOCKS = {'paragraph', 'listitem', 'row', 'LabelText'}
NATIVE_INPUTS = {'Date', 'DateTime', 'InputTime'}
CONTEXT_LOSS = re.compile(
	r'Execution context was destroyed|Cannot find context|Cannot find default execution context|'
	r'Inspected target navigated|Target closed|No frame'
)
CDP_TIMEOUT_MS = 15_000  # Pi page.evaluate bounds execution in Chrome by operationTimeoutMs (default 15 s)
EVENT_BUFFER = 500  # browser-harness daemon's own event buffer size
SURROGATE = re.compile('[\ud800-\udfff]')  # lone halves of a cut emoji: Python's utf-8 stdout refuses them


def norm(s: Any) -> str:
	"""Text as the page shows it: runs of the whitespace HTML collapses become one space. Non-breaking spaces (U+00A0,
	U+202F) inside the text stay: a user copying the text gets them, and exact-string answers need them. At the ends
	they go, as all whitespace does, so a '&nbsp;' spacer is no text."""
	if isinstance(s, bool):  # JavaScript String(true) is 'true'
		s = 'true' if s else 'false'
	return re.sub(r'[ \t\n\r\f﻿]+', ' ', '' if s is None else str(s)).strip()


def fold(s: str) -> str:
	"""For matching only, never printed: every whitespace run one space, lowercased, as VISIBLE_JS folds the page text."""
	return re.sub(r'[\s﻿]+', ' ', s).lower()


def clip(s: str, n: int) -> str:
	return f'{s[:n]}…' if len(s) > n else s


def quote(s: str) -> str:
	"""JSON.stringify of a string (it escapes lone surrogates as \\udXXX)."""
	return SURROGATE.sub(lambda m: f'\\u{ord(m.group()):04x}', json.dumps(s, ensure_ascii=False))


def well_formed(s: str) -> str:
	"""What console.log writes: lone surrogates become U+FFFD."""
	return SURROGATE.sub('\ufffd', s)


def val(o: Any) -> Any:
	"""n.role?.value, n.name?.value: the value of an AXValue, or None."""
	return o.get('value') if isinstance(o, dict) else None


def prop(n: dict, name: str) -> Any:
	return next(((p.get('value') or {}).get('value') for p in n.get('properties') or [] if p.get('name') == name), None)


def is_context_loss(e: BaseException) -> bool:
	return bool(CONTEXT_LOSS.search(str(e)))


def now() -> float:
	return time.monotonic() * 1000


class Printed(str):
	"""A line the call already printed: the REPL's echo of the returned value stays empty."""


# Appended to the system prompt in ultrafast mode.
AX_PROMPT = """

Ultrafast: the global `bu` in the python REPL. Each model call costs ~1 s, so chain everything you already know into one python call.
- Look: goto_url(url); bu.state() prints the page in order and returns that text: [id] role "name" = value plus states, ## headings and visible text; * marks ids new since the last look. After a python call whose bu actions reached the page, the state is printed automatically.
  Ids are Chrome backendNodeIds: they work in bu.* and in every CDP DOM command.
- Act: bu.click(1400); bu.type(812, 'Zurich'); bu.type(830, 'Oct 14', enter=True). type replaces the field's text. bu.type(id, 'Canada') also picks a native select option; never click a select.
  Each action prints one line: navigated to <url> / page changed / no change. Autocomplete: type, look, then click the suggestion.
- Raw: upload to a file line with cdp('DOM.setFileInputFiles', backendNodeId=id, files=[os.path.abspath('cv.txt')]); keys cdp('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27) then the same with type='keyUp'; drag with Input.dispatchMouseEvent mousePressed, mouseMoved, mouseReleased.
- If a helper fails once, do it raw. Read data with js(...), but confirm an outcome with bu.state() (visible text only), not innerText. Never add blind sleeps (time.sleep, wait()): actions and bu.state() wait for the page; for a specific condition use wait_for_element(selector).
- alert/confirm/prompt/beforeunload dialogs are accepted automatically; their text is printed as [dialog ...].
"""

# URL, title, document identity, a counter of DOM mutations (style aside) and form input/change events. Same-origin
# iframes (any depth) count as the page: Pi watched only the top document, so a click in jqueryui.com's datepicker iframe
# printed "no change" while the calendar moved. A frame document the probe has not seen yet (a frame navigated) is a
# change too. Cross-origin frames cannot be watched from here.
PROBE_JS = r"""() => {
  const w = window;
  const watch = (win, counted) => {
    const doc = win.document;
    if (doc.__buWatched) return;
    doc.__buWatched = true;
    if (counted) {
      w.__buLast = performance.now();
      w.__buN++;
    }
    // The action highlight's own overlay is not the page reacting. A style change counts only as the first
    // on its element in 200 ms: a menu shown via style.display is a change, an animation loop goes quiet.
    const own = (n) => n.hasAttribute?.('data-browser-use-interaction-highlight');
    const styled = new WeakMap();
    new MutationObserver((records) => {
      const now = performance.now();
      let real = false;
      for (const r of records) {
        if (own(r.target) || Array.from(r.addedNodes).concat(Array.from(r.removedNodes)).some(own)) continue;
        // Writing an attribute's current value changes nothing (Google Flights rewrites a class every frame).
        if (r.attributeName && r.oldValue === r.target.getAttributeNS(r.attributeNamespace, r.attributeName)) continue;
        if (r.attributeName !== 'style') real = true;
        else if (now - (styled.get(r.target) ?? -1e9) > 200) real = true;
        if (r.attributeName === 'style') styled.set(r.target, now);
      }
      if (real) {
        w.__buLast = now;
        w.__buN++;
      }
    }).observe(doc, {subtree: true, childList: true, attributes: true, attributeOldValue: true, characterData: true});
    for (const type of ['input', 'change']) win.addEventListener(type, () => w.__buN++, true);
  };
  const first = !w.__buObs;
  if (first) {
    w.__buObs = true;
    w.__buLast = performance.now();
    w.__buN = 0;
    w.__buDoc = Math.random();
    watch(w, false);
  }
  const frames = (win) => {
    for (let i = 0; i < win.frames.length; i++) {
      let f;
      try {
        f = win.frames[i];
        if (!f.document) continue;
      } catch {
        continue; // cross-origin
      }
      watch(f, !first);
      frames(f);
    }
  };
  frames(w);
  return {
    idle: performance.now() - w.__buLast,
    ready: document.readyState,
    url: location.href,
    title: document.title,
    n: w.__buN,
    doc: w.__buDoc,
    files: (() => {
      const check = (win) => {
        try {
          if (win.document?.querySelector('input[type=file]')) return true;
        } catch(e) { return true; }
        for (let i = 0; i < win.frames.length; i++) {
          try {
            if (check(win.frames[i])) return true;
          } catch(e) { return true; }
        }
        return false;
      };
      return check(w);
    })(),
    modals: (() => {
      const check = (win) => {
        try {
          if (win.document?.querySelector('[aria-modal="true"]')) return true;
        } catch(e) { return true; }
        for (let i = 0; i < win.frames.length; i++) {
          try {
            if (check(win.frames[i])) return true;
          } catch(e) { return true; }
        }
        return false;
      };
      return check(w);
    })(),
  };
}"""

# Text actually shown, lowercased with whitespace collapsed. The AX tree keeps opacity:0 text (pre-rendered
# success banners), which agents then report as success; checkVisibility with checkOpacity drops it.
VISIBLE_JS = r"""() => {
  const out = [];
  const shown = new Map();
  const roots = [document];
  for (let i = 0; i < roots.length; i++) {
    const walk = document.createTreeWalker(roots[i], NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeType === Node.ELEMENT_NODE) {
        if (n.shadowRoot) roots.push(n.shadowRoot);
        if (n.contentDocument) roots.push(n.contentDocument); // same-origin iframe
        continue;
      }
      let e = n.parentElement;
      if (!e || !n.textContent?.trim()) continue;
      // display:contents has no box, so checkVisibility is false; its text shows through the nearest boxed ancestor.
      while (e.parentElement && getComputedStyle(e).display === 'contents') e = e.parentElement;
      if (!shown.has(e)) shown.set(e, e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}));
      if (shown.get(e)) out.push(n.textContent);
    }
  }
  return out.join(' ').replace(/\s+/g, ' ').toLowerCase();
}"""

POINT_JS = r"""function(editableCover) {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  if (!e || !e.isConnected) throw Error('Target detached');
  if (e.matches(':disabled') || e.closest('[inert]')) throw Error('Target disabled');
  if (e.matches('input[type=file]')) throw Error("File input: clicking opens the OS file chooser; upload with DOM.setFileInputFiles instead");
  if (!e.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) throw Error('Target hidden');
  const r = e.getBoundingClientRect(), x = r.x + r.width/2, y = r.y + r.height/2;
  if (!r.width || !r.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) throw Error('Target outside viewport');
  const hit = e.getRootNode().elementFromPoint(x, y);
  const textField = (n) => n && (['INPUT','TEXTAREA'].includes(n.tagName) || n.isContentEditable);
  const covered = !e.contains(hit) && !(hit && hit.contains(e) && getComputedStyle(hit).pointerEvents !== 'none' && hit.tagName === 'LABEL') && !(editableCover && textField(e) && textField(hit));
  // Inside same-origin iframes, add each frame's content-box offset to get top-level viewport coordinates.
  let px = x, py = y;
  for (let w = e.ownerDocument.defaultView; w && w.frameElement; w = w.parent) {
    const f = w.frameElement, fr = f.getBoundingClientRect(), cs = getComputedStyle(f);
    px += fr.x + f.clientLeft + parseFloat(cs.paddingLeft);
    py += fr.y + f.clientTop + parseFloat(cs.paddingTop);
  }
  return {x: px, y: py, covered};
}"""

CENTER_JS = "function(){const e=this.nodeType===1?this:this.parentElement;e.scrollIntoView({block:'center',inline:'center',behavior:'instant'});}"

# Runs before every type branch: native selects and date inputs are set directly, so they never reach POINT_JS's checks.
# CSS-hidden only (no opacity check): custom-styled widgets often keep an opacity-0 native select underneath.
KIND_JS = (
	"function(){const e=this.nodeType===1?this:this.parentElement;if(!e||!e.isConnected)throw Error('Target detached');"
	"if(e.matches(':disabled')||e.closest('[inert]'))throw Error('Target disabled');"
	"if(!e.checkVisibility({checkVisibilityCSS:true}))throw Error('Target hidden');"
	"return {tag:e.tagName,type:e.type||''};}"
)

SELECT_JS = r"""function(want){
  const n = s => String(s).replace(/\s+/g,' ').trim().toLowerCase(), opts = [...this.options].filter(o => !o.disabled);
  const pre = opts.filter(o => n(o.label).startsWith(n(want)));
  const o = opts.find(o => n(o.label) === n(want) || n(o.value) === n(want)) ?? (pre.length === 1 ? pre[0] : undefined);
  if (!o) throw Error((pre.length > 1 ? 'several options start with ' : 'no option ') + JSON.stringify(want) + '. Options: ' + (pre.length > 1 ? pre : opts).slice(0, 40).map(o => o.label).join(' | '));
  this.value = o.value;
  this.dispatchEvent(new Event('input',{bubbles:true})); this.dispatchEvent(new Event('change',{bubbles:true}));
  return o.label;
}"""

DATE_JS = (
	"function(v){const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set,old=this.value;"
	"s.call(this,v);if(this.value!==v){s.call(this,old);throw Error('Invalid native date/time value; use its ISO format');}"
	"this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}));}"
)

MOVED_JS = (
	'function(){const e=this.nodeType===1?this:this.parentElement;let a=document.activeElement;'
	'while(a&&a.shadowRoot&&a.shadowRoot.activeElement)a=a.shadowRoot.activeElement;'
	"return !!a&&a!==e&&!e.contains(a)&&(['INPUT','TEXTAREA'].includes(a.tagName)||a.isContentEditable);}"
)

ACTIVE_VALUE_JS = r"""() => {
  let a = document.activeElement;
  while (a?.shadowRoot?.activeElement) a = a.shadowRoot.activeElement;
  return a ? (a.isContentEditable ? a.innerText : (a.value ?? '')) : '';
}"""

VALUE_JS = "function(){const e=this.nodeType===1?this:this.parentElement;return e.isContentEditable?e.innerText:(e.value??'');}"


def _fit_lines(src: list[str], budget: float) -> int:
	size = 0
	for i, line in enumerate(src):
		size += len(line) + 1
		if size > budget:
			return i
	return len(src)


def _fit_overlays(lines: list[str], overlay_mask: list[bool], max_budget: int) -> list[str]:
	"""Assemble truncated page lines preserving page order while prioritizing overlay elements."""
	if max_budget <= 0:
		return []

	def marker_for(n: int, budget: int) -> str:
		full = f'... {n} lines cut here (bu.state(max=30000) or js(...))'
		if len(full) + 1 <= budget:
			return full
		short = f'... {n} lines cut'
		if len(short) + 1 <= budget:
			return short
		tiny = f'... {n} cut'
		if len(tiny) + 1 <= budget:
			return tiny
		if budget >= 4:
			return '...'
		return ''

	def make_body(kept: set[int], per_marker: int) -> list[str]:
		intervals: list[tuple[str, int]] = []
		last = -1
		for i in range(len(lines)):
			if i in kept:
				if last == -1 and i > 0:
					intervals.append(('cut', i))
				elif last != -1 and i > last + 1:
					intervals.append(('cut', i - last - 1))
				intervals.append(('line', i))
				last = i
		if last != -1 and last < len(lines) - 1:
			intervals.append(('cut', len(lines) - 1 - last))
		elif last == -1 and lines:
			intervals.append(('cut', len(lines)))

		res: list[str] = []
		for typ, val in intervals:
			if typ == 'line':
				res.append(lines[val])
			else:
				m = marker_for(val, per_marker)
				if m:
					res.append(m)
		return res

	def cost_of(b: list[str]) -> int:
		return sum(len(line) + 1 for line in b)

	def count_cuts(kept: set[int]) -> int:
		cuts = 0
		last = -1
		for i in range(len(lines)):
			if i in kept:
				if (last == -1 and i > 0) or (last != -1 and i > last + 1):
					cuts += 1
				last = i
		if (last != -1 and last < len(lines) - 1) or (last == -1 and lines):
			cuts += 1
		return cuts

	ov_indices = [i for i, ov in enumerate(overlay_mask) if ov]
	bg_indices = [i for i, ov in enumerate(overlay_mask) if not ov]

	if not ov_indices:
		num_cuts = 1
		per_marker = max_budget // num_cuts
		m = marker_for(len(lines), per_marker)
		marker_cost = len(m) + 1 if m else 0
		content_budget = max(0, max_budget - marker_cost)

		head_k = _fit_lines(lines, content_budget * 0.8)
		tail_k = _fit_lines(lines[::-1], content_budget * 0.2)
		kept = set(range(head_k)) | set(range(len(lines) - tail_k, len(lines)))
		body = make_body(kept, per_marker)
		prune_order = list(range(head_k - 1, -1, -1)) + list(range(len(lines) - tail_k, len(lines)))
		while cost_of(body) > max_budget and prune_order:
			kept.discard(prune_order.pop(0))
			body = make_body(kept, per_marker)

		for idx in range(head_k, len(lines) - tail_k):
			candidate = kept | {idx}
			cand_body = make_body(candidate, per_marker)
			if cost_of(cand_body) <= max_budget:
				kept = candidate
				body = cand_body
			else:
				break
		while cost_of(body) > max_budget and body:
			body.pop()
		return body

	candidate_kept = set(ov_indices)
	cuts = count_cuts(candidate_kept)
	ov_content_cost = sum(len(lines[i]) + 1 for i in candidate_kept)
	rem_for_markers = max(0, max_budget - ov_content_cost)
	per_marker = rem_for_markers // cuts if cuts > 0 else max_budget

	body = make_body(candidate_kept, per_marker)

	if cost_of(body) <= max_budget:
		rem = max_budget - cost_of(body)
		if rem > 0 and bg_indices:
			bg_lines = [lines[i] for i in bg_indices]
			head_k = _fit_lines(bg_lines, rem * 0.8)
			tail_k = _fit_lines(bg_lines[::-1], rem * 0.2)
			bg_head = bg_indices[:head_k]
			bg_tail = bg_indices[len(bg_indices) - tail_k :]

			candidate_kept |= set(bg_head) | set(bg_tail)
			body = make_body(candidate_kept, per_marker)

			bg_prune = list(bg_head[::-1]) + list(bg_tail)
			while cost_of(body) > max_budget and bg_prune:
				candidate_kept.discard(bg_prune.pop(0))
				body = make_body(candidate_kept, per_marker)

			for idx in bg_indices[head_k : len(bg_indices) - tail_k]:
				candidate = candidate_kept | {idx}
				cand_body = make_body(candidate, per_marker)
				if cost_of(cand_body) <= max_budget:
					candidate_kept = candidate
					body = cand_body
				else:
					break
		while cost_of(body) > max_budget and body:
			body.pop()
		return body
	else:
		ov_lines = [lines[i] for i in ov_indices]
		cuts_est = 2 if len(lines) > len(ov_indices) else 1
		per_m = max_budget // cuts_est
		m = marker_for(len(ov_lines), per_m)
		m_cost = (len(m) + 1) * cuts_est if m else 0
		content_budget = max(0, max_budget - m_cost)
		head_k = _fit_lines(ov_lines, content_budget * 0.8)
		tail_k = _fit_lines(ov_lines[::-1], content_budget * 0.2)
		kept = set(ov_indices[:head_k]) | set(ov_indices[len(ov_indices) - tail_k :])
		cuts = count_cuts(kept)
		per_m = max_budget // cuts if cuts > 0 else max_budget
		body = make_body(kept, per_m)

		prune_order = list(ov_indices[head_k - 1 : -1 : -1]) + list(ov_indices[len(ov_indices) - tail_k :])
		while cost_of(body) > max_budget and prune_order:
			kept.discard(prune_order.pop(0))
			cuts = count_cuts(kept)
			per_m = max_budget // cuts if cuts > 0 else max_budget
			body = make_body(kept, per_m)

		for idx in ov_indices[head_k : len(ov_indices) - tail_k]:
			candidate = kept | {idx}
			cand_body = make_body(candidate, per_m)
			if cost_of(cand_body) <= max_budget:
				kept = candidate
				body = cand_body
			else:
				break
		while cost_of(body) > max_budget and body:
			body.pop()
		return body


class AxHelpers:
	"""State print and id-based actions on Chrome's accessibility tree. Raw cdp()/js() stays available."""

	def __init__(
		self, cdp: Callable[..., dict], log: Callable[[str], None] = print, on_event: Callable[[dict], None] | None = None
	):
		"""on_event: called with every daemon event bu reads (the worker's captcha solver state)."""
		from browser_harness import helpers

		def pi_cdp(method: str, session_id: str | None = None, **params: Any) -> dict:
			try:
				return cdp(method, session_id, **params)
			except RuntimeError as e:
				# The daemon sends CDP's error as str(dict); Pi's cdp.ts: 'CDP -32000: No node with given id found'.
				err = str(e)
				try:
					err = ast.literal_eval(err) if err.startswith('{') else err
				except (ValueError, SyntaxError):
					pass
				if isinstance(err, dict) and 'code' in err:
					raise RuntimeError(f'CDP {err["code"]}: {err.get("message")}') from None
				raise

		self.cdp, self.log, self._ipc, self._on_event = pi_cdp, log, helpers._send, on_event
		self.inflight: dict[str, dict[str, float]] = {}
		self.last_net: dict[str, float] = {}
		# The net error of each session's last failed document load (a 401 Basic Auth challenge, DNS, TLS): Chrome then
		# shows chrome-error://chromewebdata/, often with an empty accessibility tree that says nothing about why.
		self.nav_errors: dict[str, str] = {}
		self.dialogs: list[str] = []
		# Role and name of every id in the last print: marks new ids and names targets in action lines.
		self.last: dict[int, tuple[str, str]] = {}
		# Set by every action; the worker prints the state after that cell.
		self.acted = False
		# When the last action's settle began, 0 after a failed action.
		self.acted_at = 0.0
		self.events: deque = deque(maxlen=EVENT_BUFFER)  # what drain_events() returns to the agent
		self._lock = threading.Lock()
		self._pool = ThreadPoolExecutor(8)  # Pi's Promise.all
		sys.setrecursionlimit(max(sys.getrecursionlimit(), 20_000))  # state() walks the AX tree recursively
		# An open alert/confirm blocks the page and every CDP call on it: watch events in the background.
		threading.Thread(target=self._watch, daemon=True).start()

	# --- CDP events (Pi: an observeEvent tap; here: the daemon's event buffer) ---

	def _watch(self) -> None:
		while True:
			try:
				self._pump()
				time.sleep(0.025)
			except Exception:  # - daemon not up yet or restarting
				time.sleep(0.5)

	def _pump(self) -> None:
		with self._lock:
			events = self._ipc({'meta': 'drain_events'})['events']
			for e in events:
				self._observe(e.get('method', ''), e.get('params') or {}, e.get('session_id'))
				if self._on_event:
					self._on_event(e)
			self.events.extend(events)

	def _observe(self, method: str, params: dict, session: str | None) -> None:
		# An open alert/confirm blocks the page and every CDP call on it: accept it and report its text.
		if method == 'Page.javascriptDialogOpening':
			self.dialogs.append(f'[dialog {params.get("type")}] {quote(clip(params.get("message", ""), 300))} (accepted)')
			try:
				self.cdp(
					'Page.handleJavaScriptDialog',
					session_id=session,
					accept=True,
					promptText=params.get('defaultPrompt', ''),
					_response_timeout=5,
				)
			except Exception:
				pass
			return
		if method == 'Target.detachedFromTarget':
			gone = params.get('sessionId')
			self.inflight.pop(gone, None)
			self.last_net.pop(gone, None)
			self.nav_errors.pop(gone, None)
			return
		if not session or not method.startswith('Network.'):
			return
		if params.get('type') == 'Document':
			if method == 'Network.requestWillBeSent':
				self.nav_errors.pop(session, None)
			elif method == 'Network.loadingFailed' and params.get('errorText'):
				self.nav_errors[session] = str(params['errorText'])
		m = self.inflight.setdefault(session, {})
		if method == 'Network.requestWillBeSent':
			if params.get('type', '') not in ('WebSocket', 'EventSource', 'Media', 'Ping', 'Manifest'):
				m[params.get('requestId')] = now()
		elif method in ('Network.loadingFinished', 'Network.loadingFailed'):
			m.pop(params.get('requestId'), None)
		else:
			return
		self.last_net[session] = now()

	def drain_events(self) -> list[dict]:
		"""drain_events() for the agent: the events bu already read, then the rest."""
		try:
			self._pump()
		except Exception:
			pass
		with self._lock:
			out = list(self.events)
			self.events.clear()
		return out

	def _track_network(self) -> str | None:
		"""In-flight requests of the attached session (the daemon enables Network on it). Returns its session id."""
		self._pump()
		return self._ipc({'meta': 'session'}).get('session_id')

	def _nav_error(self, url: Any) -> str | None:
		"""The net error behind Chrome's error page at url (None for any other page or when unknown)."""
		if not str(url).startswith('chrome-error:'):
			return None
		try:
			session = self._track_network()
		except Exception:
			return None
		with self._lock:
			return self.nav_errors.get(session) if session else None

	# --- page probes ---

	def _evaluate(self, fn: str) -> Any:
		r = self.cdp(
			'Runtime.evaluate',
			expression=f'({fn})()',
			timeout=CDP_TIMEOUT_MS,
			awaitPromise=True,
			returnByValue=True,
			userGesture=True,
		)
		if r.get('exceptionDetails'):
			d = r['exceptionDetails']
			raise RuntimeError((d.get('exception') or {}).get('description') or d.get('text'))
		return (r.get('result') or {}).get('value')

	def _probe(self) -> dict:
		return self._evaluate(PROBE_JS)

	def settle(self, cap_ms: float = 800, quiet_ms: float = 80, since: float = 0) -> dict:
		"""Event-based wait, never a fixed sleep: document parsed, no fresh in-flight requests
		(older than 1.5 s are treated as long-poll/analytics), and no DOM mutation for quiet_ms. Bounded by cap_ms."""
		cap, quiet, start = cap_ms, quiet_ms, now()
		try:
			session = self._track_network()
		except Exception:
			session = None
		limit, pending, probe = cap, 0, None

		def inflight() -> int:
			if not session:
				return 0
			with self._lock:
				return sum(now() - t < 1500 for t in self.inflight.get(session, {}).values())

		def net_busy() -> bool:
			nonlocal pending
			try:
				self._pump()
			except Exception:
				pass
			pending = inflight()
			return pending > 0 or ((now() - self.last_net.get(session, 0)) if session else quiet) < quiet

		while now() - start < limit:
			try:
				probe = self._probe()
				if probe['ready'] == 'loading':
					limit = max(cap, 3000)  # navigations need longer than in-page updates
				probe['idle'] = min(probe['idle'], now() - (since or start))  # quiet must be observed after this action began
				if probe['ready'] != 'loading' and probe['idle'] >= quiet and not net_busy():
					return {'why': 'quiet', 'pending': pending, 'ms': now() - start, 'probe': probe}
			except Exception as e:
				# Navigation in progress: wait for the new document. Anything else ends the wait, never the action.
				if not is_context_loss(e):
					return {'why': 'error', 'pending': pending, 'ms': now() - start}
				probe = None
			# Probe again once the DOM can have been quiet for quiet_ms; wait out in-flight requests here, not in the page.
			time.sleep((max(20, quiet - probe['idle']) if probe and probe['ready'] != 'loading' else 40) / 1000)
			while probe and probe['idle'] >= quiet and net_busy() and now() - start < limit:
				time.sleep(0.02)
		return {'why': 'cap', 'pending': inflight(), 'ms': now() - start}

	def _flush_dialogs(self) -> str:
		with self._lock:  # the watcher thread appends
			out, self.dialogs[:] = ''.join(f'\n{d}' for d in self.dialogs), []
		return out

	def _visible_text(self) -> str:
		return self._evaluate(VISIBLE_JS)

	def _info(self) -> dict:
		return self._evaluate('() => ({url: location.href, title: document.title})')

	def _capture(self) -> list[dict]:
		"""AX trees of the main frame and of every same-process child frame (other frames fail and are skipped)."""
		for i in range(21):
			try:
				nodes = self.cdp('Accessibility.getFullAXTree')['nodes']
				children: list[tuple[str, str]] = []

				def walk(tree: dict) -> None:
					for child in tree.get('childFrames') or []:
						children.append((child['frame'].get('url', ''), child['frame']['id']))
						walk(child)

				walk(self.cdp('Page.getFrameTree')['frameTree'])

				def frame(c: tuple[str, str]) -> dict:
					try:
						return {'url': c[0], 'id': c[1], 'nodes': self.cdp('Accessibility.getFullAXTree', frameId=c[1])['nodes']}
					except Exception:
						return {'url': c[0], 'id': c[1], 'nodes': []}

				return [{'url': '', 'id': '', 'nodes': nodes}, *self._pool.map(frame, children)]
			except Exception as e:
				if i >= 20 or not is_context_loss(e):
					raise
				time.sleep(0.05)
		raise AssertionError('unreachable')

	def _dom_extras(self) -> tuple[list[dict], set[int]]:
		for i in range(21):
			try:
				files: list[dict] = []
				modals: set[int] = set()
				doc = self.cdp('DOM.getFlattenedDocument', depth=-1, pierce=True)
				for n in doc.get('nodes') or []:
					attrs = n.get('attributes') or []
					tag = n.get('nodeName', '').lower()
					for j in range(0, len(attrs), 2):
						k, v = attrs[j].lower(), attrs[j + 1].lower()
						if k == 'aria-modal' and v == 'true':
							modals.add(n['backendNodeId'])
						if tag == 'input' and k == 'type' and v == 'file':
							files.append(n)
				return files, modals
			except Exception as e:
				if i >= 20 or not is_context_loss(e):
					self.log(f'_dom_extras failed: {e}')
					return [], set()
				time.sleep(0.05)
		return [], set()

	def state(self, max: int = 3000, prioritize_overlays: bool = True) -> Printed:  # - Pi's option name
		"""The page as one list in page order.

		Args:
			max: Maximum character budget for the page state body lines (excluding header and
				[/state] delimiter). Defaults to 3000. When lines are truncated, cut markers
				are accounted for within this budget. For smaller budgets where the standard cut marker
				(~55 characters) would exceed the limit, an adaptive shorter cut marker (e.g. "... N lines cut"
				or "...") is used, guaranteeing that body cost never exceeds max.
			prioritize_overlays: When True (default) and the snapshot exceeds max budget, dialogs,
				alertdialogs, menus, listboxes, options, and aria-modal="true" elements (including
				hidden file uploaders inside them) are prioritized over background page content.
				Overlay elements are preserved in page order along with their cut markers as long
				as their total cost fits within max. If overlay elements alone (including cut markers)
				exceed max, an 80% head / 20% tail truncation is applied to the overlay lines, with
				zero space allocated to background content. When prioritize_overlays is False,
				standard 80% head / 20% tail truncation is applied across all page lines regardless
				of overlay status.
		"""
		# A look right after an action continues that action's quiet window instead of starting a new one.
		since = self.acted_at if self.acted else 0
		self.acted = False  # a look after the last action replaces the automatic print
		settled = self.settle(cap_ms=3000, since=since)
		# The settle probe already has URL and title, and says whether a file input needs looking up.
		probe = settled.get('probe')
		frames_job = self._pool.submit(self._capture)
		info_job = None if probe else self._pool.submit(self._info)
		visible_job = self._pool.submit(self._visible_text)
		need_dom = not probe or probe.get('files') is not False or (prioritize_overlays and probe.get('modals') is not False)
		extras_job = self._pool.submit(self._dom_extras) if need_dom else None
		frames = frames_job.result()
		info = probe or info_job.result()
		try:
			visible = visible_job.result()
		except Exception:
			visible = None
		try:
			files, aria_modals = extras_job.result() if extras_job else ([], set())
		except Exception:
			files, aria_modals = [], set()
		previous = self.last
		self.last = {}
		lines: list[str] = []
		overlay_mask: list[bool] = []
		text: list[str] = []
		text_ov: bool = False

		def flush() -> None:
			nonlocal text_ov
			if text:
				lines.append(' '.join(text))
				overlay_mask.append(text_ov)
				text.clear()
				text_ov = False

		overlay_frame_ids: set[str] = set()
		for frame in frames:
			by_id = {n['nodeId']: n for n in frame['nodes']}
			start = len(lines)

			def walk(n: dict | None, inside: str, overlay: bool = False) -> None:
				nonlocal text_ov
				if not n:
					return
				role = val(n.get('role'))
				role = '' if role is None else str(role)
				is_overlay = overlay or (role in OVERLAYS) or bool(prop(n, 'modal')) or (n.get('backendDOMNodeId') in aria_modals)
				if is_overlay and 'frame' in role.lower() and n.get('backendDOMNodeId'):
					try:
						desc = self.cdp('DOM.describeNode', backendNodeId=n['backendDOMNodeId'])
						fid = (desc.get('node') or {}).get('frameId')
						if fid:
							overlay_frame_ids.add(fid)
					except Exception:
						pass
				name = norm(val(n.get('name')))
				kids = n.get('childIds') or []
				if n.get('ignored'):
					for c in kids:
						walk(by_id.get(c), inside, is_overlay)
					return
				if role == 'StaticText':
					t = fold(name)
					if t and t not in inside and (visible is None or t in visible):
						if text and text_ov != is_overlay:
							flush()
						text_ov = is_overlay
						text.append(name)
					return
				if role == 'heading' and name:
					flush()
					lines.append(f'## {name}')
					overlay_mask.append(is_overlay)
					for c in kids:
						walk(by_id.get(c), fold(name), is_overlay)
					return
				id = n.get('backendDOMNodeId')
				# Focusable wrappers (tabindex=-1 dialogs, <main>) are only controls if they carry a name, value or editing.
				focusable = (
					prop(n, 'focusable') and role != 'RootWebArea' and (name or val(n.get('value')) or prop(n, 'editable'))
				)
				if not id or not (role in CONTROLS or focusable):
					if role not in BLOCKS:
						for c in kids:
							walk(by_id.get(c), inside, is_overlay)
						return
					flush()
					for c in kids:
						walk(by_id.get(c), inside, is_overlay)
					return flush()
				flush()
				if lines and lines[-1].lower() == name.lower():
					lines.pop()  # its label, printed as its name
					overlay_mask.pop()
				value = norm(val(n.get('value')))
				checked, expanded = prop(n, 'checked'), prop(n, 'expanded')
				states = [
					s
					for s in [
						'' if checked is None else 'unchecked' if checked == 'false' else 'checked',
						'' if expanded is None else 'expanded' if expanded else 'collapsed',
						'selected' if prop(n, 'selected') else '',
						# Chrome flags aria-disabled too, but only native disabled stops input: those are never focusable.
						'disabled' if prop(n, 'disabled') and not prop(n, 'focusable') else '',
						'focused' if prop(n, 'focused') else '',
					]
					if s
				]
				# A native <select> keeps its options in a popup child: summarize them instead of listing each.
				popup = next((c for c in map(by_id.get, kids) if c and val(c.get('role')) == 'MenuListPopup'), None)
				options: list[str] = []

				def collect(c: dict | None) -> None:
					if not c:
						return
					if val(c.get('role')) == 'option':
						options.append(norm(val(c.get('name'))))
					else:
						for k in c.get('childIds') or []:
							collect(by_id.get(k))

				collect(popup)
				shown = (
					'select'
					if popup
					else 'file'
					if role == 'button' and value
					else 'textbox'
					if role == 'generic' and prop(n, 'editable')
					else role
				)
				self.last[id] = (shown, name)
				more = f' | … {len(options) - 5} more' if len(options) > 5 else ''
				lines.append(
					('*' if previous and id not in previous else '')
					+ f'[{id}] {shown}'
					+ (f' "{clip(name, 150)}"' if name else '')
					+ (f' = {quote(clip(value, 100))}' if value else '')
					+ (' ' + ' '.join(states) if states else '')
					+ ('  options: ' + ' | '.join(options[:5]) + more if options else '')
				)
				overlay_mask.append(is_overlay)
				if popup or role in NATIVE_INPUTS:
					return  # their children are the browser's own widget parts
				# Only what the line showed counts as said: a card link's text past the clipped name still prints.
				inside = fold(f'{inside} {clip(name, 150)} {value}')
				for c in kids:
					walk(by_id.get(c), inside, is_overlay)
				flush()

			frame_overlay = bool(frame.get('id') and frame['id'] in overlay_frame_ids)
			walk(frame['nodes'][0] if frame['nodes'] else None, '', overlay=frame_overlay)
			flush()
			if frame['url'] and len(lines) > start:
				frame_has_overlay = frame_overlay or any(overlay_mask[start:])
				lines.insert(start, f'--- frame {frame["url"]} ---')
				overlay_mask.insert(start, frame_has_overlay)
		# Styled uploaders hide their file input, which drops it from the AX tree; its id still works for uploads.
		hidden = []
		hidden_mask = []
		for f in files:
			if f['backendNodeId'] in self.last:
				continue
			attrs = f.get('attributes') or []

			def at(k: str) -> str | None:
				return next((attrs[i] for i in range(1, len(attrs), 2) if attrs[i - 1] == k), None)

			name = next((v for v in (at('aria-label'), at('name'), at('id')) if v is not None), '')
			self.last[f['backendNodeId']] = ('file', name)
			hidden.append(f'[{f["backendNodeId"]}] file "{name}" (hidden)')
			is_ov = False
			try:
				is_ov = bool(
					self._on_node(
						f['backendNodeId'],
						'function() { return !!this.closest(\'dialog, [role~=dialog], [role~=alertdialog], [aria-modal="true"], [role~=menu], [role~=listbox], [role~=option]\'); }',
					)
				)
			except Exception:
				pass
			hidden_mask.append(is_ov)
		lines[:0] = hidden
		overlay_mask[:0] = hidden_mask
		pending = settled['pending']
		header = (
			f'[state] {info["title"]} | {info["url"]}' + (f' | loading: {pending}' if pending else '') + self._flush_dialogs()
		)

		failed = self._nav_error(info['url'])
		body = lines or [
			f'(the page did not load: {failed})'
			if failed
			else '(nothing in the accessibility tree: the page is blank, or a popup, often in a cross-origin iframe, hides it; screenshot() to see it)'
		]

		# Over max, keep the top and the last fifth: a dialog's Done/Submit is usually its last line.
		# If prioritize_overlays is active and there are overlay elements (dialog, popup), prioritize them
		# so active modals and popups are not crowded out by page-background elements while preserving page order.
		if _fit_lines(body, max) < len(body):
			mask = overlay_mask if (prioritize_overlays and len(overlay_mask) == len(body)) else [False] * len(body)
			body = _fit_overlays(body, mask, max)
		out = well_formed(f'{header}\n' + '\n'.join(body) + '\n[/state]')
		self.log(out)
		return Printed(out)

	def _file_inputs(self) -> list[dict]:
		return self._dom_extras()[0]

	def _on_node(self, id: int, fn: str, argument: Any = None) -> Any:
		obj = self.cdp('DOM.resolveNode', backendNodeId=id)['object']
		if not obj.get('objectId'):
			raise RuntimeError('Node unavailable.')
		try:
			r = self.cdp(
				'Runtime.callFunctionOn',
				objectId=obj['objectId'],
				functionDeclaration=fn,
				arguments=[{} if argument is None else {'value': argument}],
				returnByValue=True,
				awaitPromise=True,
			)
			if r.get('exceptionDetails'):
				d = (r['exceptionDetails'].get('exception') or {}).get('description')
				raise RuntimeError(('Node operation failed.' if d is None else d).split('\n    at ')[0])
			return (r.get('result') or {}).get('value')
		finally:
			try:
				self.cdp('Runtime.releaseObject', objectId=obj['objectId'])
			except Exception:
				pass

	def _describe(self, id: int) -> str:
		n = self.last.get(id)
		if not n:
			return f'[{id}]'
		return f'[{id}] {n[0]}' + (f' "{clip(n[1], 60)}"' if n[1] else '')

	def _point(self, id: int, editable_cover: bool = False) -> dict:
		"""Scroll into view and return a clickable, unobstructed center point, or raise a precise reason."""
		try:
			self.cdp('DOM.scrollIntoViewIfNeeded', backendNodeId=id)
		except Exception:
			pass
		p = self._on_node(id, POINT_JS, editable_cover)
		if not p['covered']:
			return p
		# A fixed header or footer over a target near the viewport edge: the target counts as visible, so
		# scrollIntoViewIfNeeded leaves it there (demoqa.com's footer). Centered, it is usually clear.
		try:
			self._on_node(id, CENTER_JS)
			p = self._on_node(id, POINT_JS, editable_cover)
		except Exception:
			pass
		if not p['covered']:
			return p
		try:
			hit = self.cdp('DOM.getNodeForLocation', x=math.floor(p['x'] + 0.5), y=math.floor(p['y'] + 0.5))
		except Exception:
			hit = None
		try:
			tree = self.cdp('Accessibility.getPartialAXTree', backendNodeId=hit['backendNodeId']) if hit else None
		except Exception:
			tree = None
		# The node under the point and its ancestors: name the nearest one with a name or a dialog role.
		nodes = (tree or {}).get('nodes') or []
		by_id = {a['nodeId']: a for a in nodes}
		top = next((a for a in nodes if hit and a.get('backendDOMNodeId') == hit.get('backendNodeId')), None)
		n = top
		while (
			n
			and val(n.get('role')) != 'RootWebArea'
			and (n.get('ignored') or not (norm(val(n.get('name'))) or 'dialog' in str(val(n.get('role')))))
		):
			n = by_id.get(n['parentId']) if n.get('parentId') else None

		# A nameless overlay: name it by its own text instead of the page it sits on.
		def text(x: dict | None) -> str:
			x = x or {}
			first = next((c for c in map(by_id.get, x.get('childIds') or []) if c and val(c.get('role')) == 'StaticText'), {})
			return norm(val(x.get('name'))) or norm(val(first.get('name')))

		if not n or val(n.get('role')) == 'RootWebArea':
			n = top
		who = (
			f'[{n.get("backendDOMNodeId")}] {val(n.get("role"))} "{clip(text(n), 60)}"'
			if n
			else f'[{hit["backendNodeId"]}]'
			if hit
			else 'another element'
		)
		raise RuntimeError(f'Target covered by {who}; nothing was clicked')

	def _click_at(self, x: float, y: float) -> None:
		"""Pi page.clickAt without its mouseMoved: browser-harness tabs stay in the background, where Chrome answers
		mouseMoved only after ~5 s (measured, headless Chrome). Press and release move the pointer anyway."""
		if not all(math.isfinite(v) for v in (x, y)):
			raise ValueError('Coordinates must be finite.')
		self.cdp('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button='left', clickCount=1)
		self.cdp('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button='left', clickCount=1)

	def _act(self, op: str, id: int, body: Callable[[], str]) -> Printed:
		"""Runs one action on id and prints one line: navigated to <url> / page changed / no change."""
		# Set before acting: a failed action still gets the state printed after its cell.
		self.acted = True
		self.acted_at = 0
		try:
			self._track_network()
		except Exception:
			pass
		try:
			before = self._probe()
		except Exception:
			before = None
		try:
			detail = body()
		except Exception as e:
			raise RuntimeError(well_formed(f'{op} {self._describe(id)} failed: {e}')) from None
		self.acted_at = now()
		settled = self.settle()
		line = well_formed(
			f'[ok] {op} {self._describe(id)}{detail} -> {self._change(before, settled.get("probe"))}{self._flush_dialogs()}'
		)
		self.log(line)
		return Printed(line)

	def _change(self, before: dict | None, after: dict | None = None) -> str:
		if after is None:
			try:
				after = self._probe()
			except Exception:
				after = None
		if not before or not after:
			return 'page changed'
		if after['doc'] != before['doc'] or after['url'] != before['url']:
			failed = self._nav_error(after['url'])
			return f'navigated to {after["url"]}' + (f' ({failed})' if failed else '')
		return 'page changed' if after['n'] != before['n'] else 'no change'

	def click(self, id: int) -> Printed:
		def body() -> str:
			p = self._point(id)
			self._click_at(p['x'], p['y'])
			return ''

		return self._act('click', id, body)

	def type(self, id: int, text: str, enter: bool = False) -> Printed:
		if not isinstance(text, str):
			raise TypeError('type needs a string.')

		def body() -> str:
			kind = self._on_node(id, KIND_JS)
			if kind['tag'] == 'SELECT':
				return f' = {quote(self._on_node(id, SELECT_JS, text))}'
			if kind['tag'] == 'INPUT' and kind['type'] in ('date', 'time', 'datetime-local', 'month', 'week'):
				self._on_node(id, DATE_JS, text)
				return f' = {quote(text)}'
			p = self._point(id, True)
			self._click_at(p['x'], p['y'])
			# Comboboxes often move focus to their own overlay input on click; type there, not into the hidden original.
			try:
				moved = bool(self._on_node(id, MOVED_JS))
			except Exception:
				moved = False
			if not moved:
				try:
					self.cdp('DOM.focus', backendNodeId=id)
				except Exception:
					pass
			a = {'key': 'a', 'code': 'KeyA', 'windowsVirtualKeyCode': 65, 'modifiers': 2}
			self.cdp('Input.dispatchKeyEvent', type='rawKeyDown', **a, commands=['selectAll'])
			self.cdp('Input.dispatchKeyEvent', type='keyUp', **a)
			if text == '':
				self._key('Backspace', 8)
			else:
				# Datepickers and autocompletes react to key events, which insertText never sends: type the last character as a key.
				*chars, last = text
				if chars:
					self.cdp('Input.insertText', text=''.join(chars))
				self.cdp('Input.dispatchKeyEvent', type='keyDown', key=last, text=last)
				self.cdp('Input.dispatchKeyEvent', type='keyUp', key=last)
			try:
				actual = self._evaluate(ACTIVE_VALUE_JS) if moved else self._on_node(id, VALUE_JS)
			except Exception:
				actual = None
			if enter:
				self._key('Enter', 13, '\r')
			# A password field's value never goes into the action line: it lands in the trace, logs and the judge's prompt
			secret = kind['tag'] == 'INPUT' and kind['type'] == 'password'
			shown = (lambda v: f'<{len(v)} characters, hidden>') if secret else (lambda v: quote(clip(v, 60)))
			return (
				f' = {shown(text)}'
				+ (' (into the focused overlay input)' if moved else '')
				+ (f' (field now shows {shown(actual)})' if actual is not None and actual != text else '')
				+ (' +Enter' if enter else '')
			)

		return self._act('type', id, body)

	def _key(self, key: str, key_code: int, text: str | None = None) -> None:
		k = {'key': key, 'code': key, 'windowsVirtualKeyCode': key_code, 'nativeVirtualKeyCode': key_code}
		self.cdp('Input.dispatchKeyEvent', type='rawKeyDown', **k)
		if text:
			self.cdp('Input.dispatchKeyEvent', type='char', **k, text=text, unmodifiedText=text)
		self.cdp('Input.dispatchKeyEvent', type='keyUp', **k)
