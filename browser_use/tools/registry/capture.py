"""Element capture for trajectory recording (event schema v4).

For every index-bearing action the registry executes, this module captures a rich,
self-describing record of the element the agent interacted with, so that an offline
pipeline (web-knowledge clean_logs/build_selectors) can produce robust selectors for
the onboarding-tour SDK without ever guessing.

Three things distinguish v4 capture from the legacy (12_6) element logging:

1.  Interactive-ancestor retargeting — the CDP hit node is often a decorative leaf
	(an icon <svg>, a text-overlay <div>) inside the element that actually owns the
	click. We climb to the real interaction target before recording anything.

2.  Anchor detection — alongside the interaction target we record its best
	text-bearing descendant (heading or title line). Visible text is the identity
	signal that survives class churn and tag drift, so downstream selector
	strategies key on it.

3.  Capture-time selector verification — candidate selectors are generated here and
	immediately tested against the live page over CDP, with `this` bound to the
	exact node the agent used. Each candidate is logged with how many elements it
	matches and what the tour SDK's resolution algorithm would actually pick
	(exact / descendant / ancestor / other), turning offline selector ranking from
	a guess into a measurement.

Everything here is best-effort: any failure degrades to a smaller record, never to a
failed action.
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

if TYPE_CHECKING:
	from browser_use.browser import BrowserSession

logger = logging.getLogger(__name__)

# ─── Tunables ────────────────────────────────────────────────────────────────

MAX_CLIMB_LEVELS = 6
MAX_ANCHOR_DEPTH = 4
MAX_ANCESTOR_SUMMARY = 8
MAX_TEXT_LEN = 200
MAX_TEXT_FILTER_LEN = 80
VERIFY_TIMEOUT_S = 3.0

# ─── Interactivity signals ───────────────────────────────────────────────────
# "Strong" signals mean the element itself owns the interaction. Inherited
# cursor:pointer is deliberately NOT here — it propagates to every descendant of a
# clickable card, which is exactly the mis-capture we are correcting. It is used
# separately as a boundary signal (outermost contiguous pointer ancestor).

STRONG_INTERACTIVE_TAGS = {
	'button',
	'a',
	'input',
	'select',
	'textarea',
	'option',
	'summary',
	'details',
}

INTERACTIVE_ROLES = {
	'button',
	'link',
	'menuitem',
	'menuitemcheckbox',
	'menuitemradio',
	'option',
	'radio',
	'checkbox',
	'switch',
	'tab',
	'textbox',
	'combobox',
	'listbox',
	'slider',
	'spinbutton',
	'searchbox',
}

# AX state properties that only exist on interactive widgets
INTERACTIVE_AX_STATE_PROPS = {'checked', 'expanded', 'pressed', 'selected'}

SEMANTIC_CONTAINER_TAGS = {'aside', 'nav', 'main', 'header', 'footer', 'section', 'article', 'form', 'dialog'}
ARIA_CONTAINER_ROLES = {'region', 'navigation', 'contentinfo', 'complementary', 'main', 'menu', 'dialog'}
LANDMARK_SCOPE_TAGS = {'aside', 'nav', 'main', 'header', 'footer', 'form', 'dialog'}

HEADING_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

# ─── Attribute stability rules (aligned with web-knowledge build_selectors) ──

DYNAMIC_ATTRS = {
	'id',
	'aria-controls',
	'aria-expanded',
	'data-state',
	'tabindex',
	'data-orientation',
	'data-radix-collection-item',
	'data-radix-menubar-subtrigger',
	'value',
	'aria-haspopup',
	'style',
	'class',
}

STABLE_ATTRS = ['role', 'type', 'name', 'placeholder', 'data-testid', 'aria-label']

NON_UNIQUE_ATTRS = {'data-testid', 'role'}

REDUNDANT_ROLES = {
	'button': 'button',
	'a': 'link',
	'select': 'combobox',
	'input': 'textbox',
	'textarea': 'textbox',
}

DYNAMIC_VALUE_PATTERNS = [
	re.compile(r'^radix-:'),
	re.compile(r'^:r[a-z0-9]+:$'),
	re.compile(r'^react-'),
	re.compile(r'^__next'),
]

DYNAMIC_SEGMENT_PATTERNS = [
	re.compile(r'^[0-9a-f]{8}-'),  # UUID prefix
	re.compile(r'^[0-9a-f]{24}$'),  # MongoDB ObjectId
	re.compile(r'^\d+$'),  # pure numeric ID
	re.compile(r'^[A-Za-z0-9_-]{20,}$'),  # long opaque tokens
]


# ─── Small helpers ───────────────────────────────────────────────────────────


def _is_element(node: EnhancedDOMTreeNode | None) -> bool:
	return node is not None and node.node_type == NodeType.ELEMENT_NODE


def _tag(node: EnhancedDOMTreeNode) -> str:
	return (node.tag_name or '').lower()


def _attrs(node: EnhancedDOMTreeNode) -> dict[str, str]:
	return node.attributes or {}


def _is_dynamic_value(val: str) -> bool:
	return any(p.search(val) for p in DYNAMIC_VALUE_PATTERNS)


def _own_text(node: EnhancedDOMTreeNode) -> str:
	"""Full descendant text of a node, stripped."""
	try:
		return (node.get_all_children_text() or '').strip()
	except Exception:
		return ''


def _first_line(text: str) -> str:
	return text.split('\n')[0].strip() if text else ''


def _cursor(node: EnhancedDOMTreeNode) -> str | None:
	if node.snapshot_node:
		return node.snapshot_node.cursor_style
	return None


def _ax_role(node: EnhancedDOMTreeNode) -> str | None:
	return node.ax_node.role if node.ax_node else None


def _ax_name(node: EnhancedDOMTreeNode) -> str | None:
	return node.ax_node.name if node.ax_node else None


def _escape_attr(value: str) -> str:
	return value.replace('"', '\\"')


def _attr_selector(attr: str, value: str) -> str:
	return f'[{attr}="{_escape_attr(value)}"]'


def _stable_attrs(node: EnhancedDOMTreeNode) -> dict[str, str]:
	"""STABLE_ATTRS present on the node with non-dynamic values, in priority order."""
	out: dict[str, str] = {}
	attrs = _attrs(node)
	for key in STABLE_ATTRS:
		val = attrs.get(key)
		if val is not None and val != '' and not _is_dynamic_value(str(val)):
			out[key] = str(val)
	return out


def _stable_data_attrs(node: EnhancedDOMTreeNode) -> dict[str, str]:
	"""Stable, uniquely-identifying data-* attributes (excludes data-testid and radix internals)."""
	out: dict[str, str] = {}
	for key, val in _attrs(node).items():
		if not key.startswith('data-'):
			continue
		if key in DYNAMIC_ATTRS or key.startswith('data-radix') or key == 'data-testid':
			continue
		if val is None or val == '':
			continue
		sval = str(val)
		if _is_dynamic_value(sval) or any(p.search(sval) for p in DYNAMIC_SEGMENT_PATTERNS):
			continue
		out[key] = sval
	return out


# ─── 1. Interactive-ancestor retargeting ────────────────────────────────────


def _has_strong_interactive_signal(node: EnhancedDOMTreeNode) -> str | None:
	"""Return the signal name if this node owns its interaction, else None."""
	if not _is_element(node):
		return None

	if _tag(node) in STRONG_INTERACTIVE_TAGS:
		return 'interactive-tag'

	if getattr(node, 'has_js_click_listener', False):
		return 'js-listener'

	attrs = _attrs(node)
	if attrs:
		if attrs.get('role') in INTERACTIVE_ROLES:
			return 'role-attr'
		if any(a in attrs for a in ('onclick', 'onmousedown', 'onmouseup', 'onkeydown', 'onkeyup')):
			return 'on-attr'
		tabindex = attrs.get('tabindex')
		if tabindex is not None:
			try:
				if int(tabindex) >= 0:
					return 'tabindex'
			except ValueError:
				pass

	if node.ax_node:
		if node.ax_node.role in INTERACTIVE_ROLES:
			return 'ax-role'
		for prop in node.ax_node.properties or []:
			try:
				if prop.name in INTERACTIVE_AX_STATE_PROPS:
					return 'ax-state'
			except (AttributeError, ValueError):
				continue

	return None


def resolve_interaction_target(node: EnhancedDOMTreeNode) -> tuple[EnhancedDOMTreeNode, dict[str, Any]]:
	"""Climb from the CDP hit node to the element that actually owns the interaction.

	Two passes over the ancestor chain (capped at MAX_CLIMB_LEVELS, stopping at body):

	1. Strong signals — first ancestor (including the node itself) that is an
	   interactive tag, has a real JS click listener, an interactive role, an on*
	   attribute, a non-negative tabindex, or interactive AX state.
	2. Cursor boundary — if nothing owns the interaction explicitly (typical for
	   framework-delegated handlers like React's), and the hit node's computed
	   cursor is 'pointer', take the OUTERMOST contiguous ancestor whose cursor is
	   still 'pointer'. cursor inherits, so that boundary is where clickability was
	   declared (e.g. a Tailwind `cursor-pointer` card).

	Returns (target, retarget_info).
	"""
	chain: list[EnhancedDOMTreeNode] = []
	current: EnhancedDOMTreeNode | None = node
	level = 0
	while current is not None and level <= MAX_CLIMB_LEVELS and _tag(current) not in ('body', 'html'):
		if _is_element(current):
			chain.append(current)
		current = current.parent_node
		level += 1

	# Pass 1: strong ownership signals
	for i, candidate in enumerate(chain):
		signal = _has_strong_interactive_signal(candidate)
		if signal:
			return candidate, {
				'applied': i > 0,
				'reason': signal,
				'levels': i,
			}

	# Pass 2: cursor boundary
	if chain and _cursor(chain[0]) == 'pointer':
		boundary_idx = 0
		for i in range(1, len(chain)):
			if _cursor(chain[i]) == 'pointer':
				boundary_idx = i
			else:
				break
		if boundary_idx > 0:
			return chain[boundary_idx], {
				'applied': True,
				'reason': 'cursor-boundary',
				'levels': boundary_idx,
			}

	return node, {'applied': False, 'reason': None, 'levels': 0}


# ─── 2. Anchor detection ─────────────────────────────────────────────────────


def pick_anchor(target: EnhancedDOMTreeNode) -> EnhancedDOMTreeNode | None:
	"""Best text-bearing descendant of the target — its identity anchor.

	Preference order:
	1. First heading (h1-h6 / role=heading) with non-empty text, breadth-first.
	2. The innermost element whose full text equals the target's first text line
	   (i.e. what the tour SDK's `text:` resolution would land on).

	Returns None when the target has no usable text.
	"""
	target_text = _own_text(target)
	if not target_text:
		return None

	first_line = _first_line(target_text)
	if not first_line or len(first_line) > MAX_TEXT_FILTER_LEN:
		return None

	# BFS for headings
	queue: list[tuple[EnhancedDOMTreeNode, int]] = [(target, 0)]
	heading: EnhancedDOMTreeNode | None = None
	line_matches: list[EnhancedDOMTreeNode] = []
	while queue:
		current, depth = queue.pop(0)
		if depth > MAX_ANCHOR_DEPTH:
			continue
		if _is_element(current) and current is not target:
			text = _own_text(current)
			if text:
				if heading is None and (_tag(current) in HEADING_TAGS or _attrs(current).get('role') == 'heading'):
					heading = current
				if text == first_line:
					line_matches.append(current)
		for child in current.children_nodes or []:
			queue.append((child, depth + 1))

	if heading is not None:
		return heading

	if line_matches:
		# innermost = fewest element children (mirrors the SDK tie-break)
		def n_children(n: EnhancedDOMTreeNode) -> int:
			return len([c for c in (n.children_nodes or []) if _is_element(c)])

		return min(line_matches, key=n_children)

	return None


# ─── 3. Semantic container / scope ───────────────────────────────────────────


def find_semantic_container(node: EnhancedDOMTreeNode) -> dict[str, Any] | None:
	"""Nearest semantic ancestor (landmark tag or ARIA container role) within 5 levels.

	Ported from the 12_6 fork, enriched with `heading_text` (the container's first
	text line — lets downstream emit a text-disambiguated scope like
	{css: "article", text: "Notification"}) and a `scope_css` suggestion.
	"""
	if node is None or node.parent_node is None:
		return None

	def container_record(container: EnhancedDOMTreeNode) -> dict[str, Any]:
		tag = _tag(container)
		attrs = _attrs(container)
		role = attrs.get('role')
		text = _own_text(container)

		scope_css: str | None = None
		stable = _stable_attrs(container)
		if stable:
			scope_css = tag + ''.join(_attr_selector(k, v) for k, v in stable.items())
		elif tag in LANDMARK_SCOPE_TAGS:
			scope_css = tag
		elif role and role in ARIA_CONTAINER_ROLES and not _is_dynamic_value(role):
			scope_css = f'{tag}[role="{role}"]'

		return {
			'element_name': container.node_name,
			'tag': container.tag_name,
			'attributes': {
				'name': attrs.get('name'),
				'role': role,
				'id': attrs.get('id'),
				'class': attrs.get('class'),
			},
			'text_preview': text[:50],
			'heading_text': _first_line(text)[:MAX_TEXT_FILTER_LEN] or None,
			'scope_css': scope_css,
			'xpath': container.xpath,
		}

	current = node.parent_node
	level = 0
	max_levels = 5
	while current is not None and level < max_levels and _tag(current) != 'body':
		if _tag(current) in SEMANTIC_CONTAINER_TAGS:
			return container_record(current)
		if _attrs(current).get('role') in ARIA_CONTAINER_ROLES:
			return container_record(current)
		current = current.parent_node
		level += 1

	if node.parent_node is not None and _tag(node.parent_node) != 'body':
		return container_record(node.parent_node)

	return None


# ─── 4. Selector candidate generation ────────────────────────────────────────


def _text_filter_for(node: EnhancedDOMTreeNode, anchor: EnhancedDOMTreeNode | None) -> str | None:
	"""The text used to disambiguate this node: anchor text, else first own line."""
	if anchor is not None:
		text = _first_line(_own_text(anchor))
	else:
		text = _first_line(_own_text(node))
	if text and len(text) <= MAX_TEXT_FILTER_LEN:
		return text
	return None


def build_selector_candidates(
	target: EnhancedDOMTreeNode,
	anchor: EnhancedDOMTreeNode | None,
	container: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
	"""Ordered candidate selectors for the target (best-guess first; verification re-ranks).

	Each candidate: {kind, css?, text?, scope?} — `css` + optional `text` filter
	follows the tour SDK's structured-selector semantics. `text:` candidates are
	encoded as css='*' with a text filter plus kind='text' so downstream can
	re-serialize them. `scope` is {css, text}: resolve the container by CSS narrowed
	to the one whose first text line equals `text`, then resolve `css` within it —
	the contract for text-disambiguated scopes (the only viable identity for
	icon-only controls like a gear button in a popover header).
	"""
	tag = _tag(target)
	attrs = _attrs(target)
	stable = _stable_attrs(target)
	text_filter = _text_filter_for(target, anchor)
	candidates: list[dict[str, Any]] = []

	def add(kind: str, css: str | None, text: str | None = None, scope: dict[str, str] | None = None) -> None:
		entry: dict[str, Any] = {'kind': kind}
		if css:
			entry['css'] = css
		if text:
			entry['text'] = text
		if scope:
			entry['scope'] = scope
		if entry not in candidates and (css or text):
			candidates.append(entry)

	# 1. Tag-less stable data-* attributes (survive tag drift)
	data_attrs = _stable_data_attrs(target)
	if data_attrs:
		css = ''.join(_attr_selector(k, v) for k, v in data_attrs.items())
		add('data-attrs', css, text_filter)
		if text_filter:
			add('data-attrs-bare', css)

	# 2. Compound: tag + non-unique stable attr (data-testid / non-redundant role) + text
	if tag and text_filter:
		non_unique = {
			k: v for k, v in stable.items() if k in NON_UNIQUE_ATTRS and not (k == 'role' and REDUNDANT_ROLES.get(tag) == v)
		}
		if non_unique:
			css = tag + ''.join(_attr_selector(k, v) for k, v in non_unique.items())
			add('compound', css, text_filter)
		elif tag in STRONG_INTERACTIVE_TAGS or tag in HEADING_TAGS:
			add('compound-tag', tag, text_filter)

	# 3. Structural with uniquely-specific attributes
	if tag and stable:
		unique_keys = {'name', 'placeholder', 'aria-label'} & set(stable.keys())
		specific_type = stable.get('type') in {'submit', 'search', 'file', 'range', 'color'}
		if unique_keys or specific_type:
			css = tag + ''.join(_attr_selector(k, v) for k, v in stable.items())
			add('structural', css)

	# 4. Bare text (SDK `text:` form)
	if text_filter:
		add('text', '*', text_filter)

	# 5. aria-label (SDK `aria:` form)
	aria = attrs.get('aria-label')
	if aria and aria.strip() and not _is_dynamic_value(aria):
		add('aria', f'[aria-label="{_escape_attr(aria.strip())}"]')

	# 6. href tail for anchors (only when free of dynamic segments)
	href = attrs.get('href')
	if href and href.strip():
		parsed = urlparse(href.strip())
		path = parsed.path
		segments = [s for s in path.split('/') if s]
		if segments and not any(any(p.search(seg) for p in DYNAMIC_SEGMENT_PATTERNS) for seg in segments):
			op = '$=' if not (parsed.query or parsed.fragment) else '*='
			add('href', f'{tag or ""}[href{op}"{_escape_attr("/" + "/".join(segments))}"]')

	# 7. Text-disambiguated container scope (e.g. the button inside the article
	#    headed "Notification"). The only viable identity for icon-only controls.
	if tag and container:
		heading = container.get('heading_text')
		container_tag = (container.get('tag') or '').lower()
		if heading and container_tag:
			inner_css = tag
			if stable:
				inner_css = tag + ''.join(_attr_selector(k, v) for k, v in stable.items())
			add('scoped', inner_css, text_filter, scope={'css': container_tag, 'text': heading})

	# 8. Broad structural fallback (tag + all stable attrs)
	if tag and stable:
		add('structural-broad', tag + ''.join(_attr_selector(k, v) for k, v in stable.items()))

	# 9. Bare tag, last resort
	if not candidates and tag:
		add('tag', tag, text_filter)

	return candidates


# ─── 5. Capture-time verification over CDP ───────────────────────────────────

# Runs in the page with `this` bound to the recorded element. Mirrors the tour
# SDK's resolution algorithm (_resolveCssText / text: handling) so `relation`
# reports what the SDK would actually pick at runtime:
#   exact      → resolves to the recorded element
#   descendant → resolves inside it (e.g. text: hits the inner <h2> of a card)
#   ancestor   → resolves to a wrapper of it
#   other      → resolves somewhere unrelated (selector is dead on arrival)
#   none       → no match
_VERIFY_JS = """
function(payload) {
	const self = this;
	const resolveIn = (root, cand) => {
		let nodes;
		try { nodes = Array.from(root.querySelectorAll(cand.css || '*')); }
		catch (e) { return { error: 'bad-css' }; }
		if (cand.text) {
			// Strict trimmed equality — exactly what OnboardingTour._resolveCssText does.
			const wanted = cand.text.trim();
			nodes = nodes.filter(n => (n.textContent || '').trim() === wanted);
			nodes.sort((a, b) => a.children.length - b.children.length);
		}
		const resolved = nodes.length ? nodes[0] : null;
		let relation = 'none';
		if (resolved) {
			if (resolved === self) relation = 'exact';
			else if (self.contains(resolved)) relation = 'descendant';
			else if (resolved.contains(self)) relation = 'ancestor';
			else relation = 'other';
		}
		return { count: nodes.length, relation: relation, self_index: nodes.indexOf(self) };
	};

	// Candidate-level text-disambiguated scope: containers matching scope.css whose
	// first text line equals scope.text (the {scope: {css, text}} contract).
	const resolveScoped = (cand) => {
		let containers;
		try { containers = Array.from(document.querySelectorAll(cand.scope.css)); }
		catch (e) { return { error: 'bad-scope-css' }; }
		const wanted = (cand.scope.text || '').trim();
		containers = containers.filter(c => ((c.textContent || '').trim().split('\\n')[0] || '').trim() === wanted);
		if (!containers.length) return { count: 0, relation: 'none', scope_count: 0 };
		const out = resolveIn(containers[0], { css: cand.css, text: cand.text });
		out.scope_count = containers.length;
		return out;
	};

	let scopeEl = null;
	if (payload.scope) {
		try { scopeEl = document.querySelector(payload.scope); } catch (e) { scopeEl = null; }
	}
	const scopeContainsSelf = !!(scopeEl && scopeEl.contains(self));

	return {
		scope_found: !!scopeEl,
		scope_contains_target: scopeContainsSelf,
		results: payload.candidates.map(cand => {
			if (cand.scope) return resolveScoped(cand);
			const out = resolveIn(document, cand);
			if (scopeEl) out.scoped = resolveIn(scopeEl, cand);
			return out;
		}),
	};
}
"""


async def verify_candidates(
	browser_session: 'BrowserSession',
	node: EnhancedDOMTreeNode,
	candidates: list[dict[str, Any]],
	scope_css: str | None,
) -> dict[str, Any] | None:
	"""Test candidate selectors against the live page, bound to the recorded node.

	Returns {scope_found, scope_contains_target, results: [...]} aligned with
	`candidates` by index, or None when verification was impossible.
	"""
	if not candidates:
		return None

	payload = {
		'candidates': [{'css': c.get('css'), 'text': c.get('text'), 'scope': c.get('scope')} for c in candidates],
		'scope': scope_css,
	}

	cdp_session = await browser_session.get_or_create_cdp_session(node.target_id, focus=False)
	resolved = await cdp_session.cdp_client.send.DOM.resolveNode(
		params={'backendNodeId': node.backend_node_id},
		session_id=cdp_session.session_id,
	)
	object_id = resolved.get('object', {}).get('objectId')
	if not object_id:
		return None

	result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': object_id,
			'functionDeclaration': _VERIFY_JS,
			'arguments': [{'value': payload}],
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value')


def _count_ax_duplicates(browser_session: 'BrowserSession', target: EnhancedDOMTreeNode) -> int | None:
	"""How many elements in the current selector map share the target's (AX role, AX name).

	1 means the (role, name) pair uniquely identifies the element among interactive
	elements — i.e. a `role:` selector would be unambiguous. None when the target has
	no AX name or the map is unavailable.
	"""
	role, name = _ax_role(target), _ax_name(target)
	if not role or not name:
		return None
	try:
		selector_map = browser_session._cached_selector_map  # in-fork access
	except Exception:
		return None
	if not selector_map:
		return None
	count = 0
	seen_backend_ids: set[int] = set()
	for candidate in selector_map.values():
		if candidate.backend_node_id in seen_backend_ids:
			continue
		seen_backend_ids.add(candidate.backend_node_id)
		if _ax_role(candidate) == role and _ax_name(candidate) == name:
			count += 1
	return count


# ─── 6. Record assembly ──────────────────────────────────────────────────────


def _node_summary(node: EnhancedDOMTreeNode) -> dict[str, Any]:
	text = _own_text(node)
	return {
		'tag': node.tag_name,
		'attributes': _attrs(node),
		'text_first_line': _first_line(text)[:MAX_TEXT_FILTER_LEN],
		'xpath': node.xpath,
	}


def _ancestor_summary(node: EnhancedDOMTreeNode) -> list[dict[str, Any]]:
	"""Compact tag + stable-attr chain above the target, raw material for offline synthesis."""
	out: list[dict[str, Any]] = []
	current = node.parent_node
	while current is not None and len(out) < MAX_ANCESTOR_SUMMARY and _tag(current) not in ('html',):
		if _is_element(current):
			entry: dict[str, Any] = {'tag': _tag(current)}
			stable = _stable_attrs(current)
			if stable:
				entry['stable_attrs'] = stable
			data_attrs = _stable_data_attrs(current)
			if data_attrs:
				entry['data_attrs'] = data_attrs
			out.append(entry)
		current = current.parent_node
	return out


async def build_element_record(
	node: EnhancedDOMTreeNode,
	browser_session: 'BrowserSession',
) -> dict[str, Any]:
	"""Assemble the full v4 element record for an action's resolved DOM node.

	Legacy keys (element_name, tag_name, role, node_name, attributes, xpath,
	text_content, container_node, children_node) keep their 12_6 shape so existing
	consumers (web-knowledge combine_logs) keep working; v4 data is additive.

	After retargeting, the legacy keys describe the INTERACTION TARGET (the element
	selectors should resolve to), and the original CDP hit node is preserved under
	`hit_node`.
	"""
	target, retarget = resolve_interaction_target(node)
	anchor = pick_anchor(target)
	container = find_semantic_container(target)
	scope_css = container.get('scope_css') if container else None

	candidates = build_selector_candidates(target, anchor, container)

	verification: dict[str, Any] | None = None
	try:
		verification = await asyncio.wait_for(
			verify_candidates(browser_session, target, candidates, scope_css),
			timeout=VERIFY_TIMEOUT_S,
		)
	except Exception as e:
		logger.debug(f'Selector verification skipped: {type(e).__name__}: {e}')

	if verification and verification.get('results'):
		for cand, res in zip(candidates, verification['results']):
			cand['verify'] = res

	text = _own_text(target)
	ax_name = _ax_name(target)
	anchor_text = _first_line(_own_text(anchor)) if anchor is not None else ''
	snapshot = target.snapshot_node

	record: dict[str, Any] = {
		# ── legacy (12_6-compatible) keys ──
		'element_name': target.node_name,
		'is_clickable': snapshot.is_clickable if snapshot else True,
		'is_scrollable': getattr(target, 'is_scrollable', False),
		'tag_name': target.tag_name,
		'role': _ax_role(target),
		# node_name feeds combine_logs' join AND its drop-filter; fall back to the
		# anchor/text first line so nameless-but-texted targets (clickable cards)
		# are never silently discarded downstream. An empty-string AX name (icon-only
		# button) is preserved as '' — 12_6 behavior — because None gets the event
		# dropped by load_jsonl.
		'node_name': ax_name or anchor_text or _first_line(text) or ax_name,
		'description': target.ax_node.description if target.ax_node else None,
		'attributes': _attrs(target),
		'xpath': target.xpath,
		'text_content': text[:50],
		# ── v4 additions ──
		'capture_version': 4,
		'text_full': text[:MAX_TEXT_LEN],
		'text_first_line': _first_line(text)[:MAX_TEXT_FILTER_LEN],
		'placeholder': _attrs(target).get('placeholder'),
		'ax': {
			'role': _ax_role(target),
			'name': ax_name,
			'duplicates_in_view': _count_ax_duplicates(browser_session, target),
		},
		'retarget': retarget,
		'selector_candidates': candidates,
		'scope_verification': {
			'scope_css': scope_css,
			'scope_found': verification.get('scope_found') if verification else None,
			'scope_contains_target': verification.get('scope_contains_target') if verification else None,
		},
		'ancestors': _ancestor_summary(target),
	}

	if anchor is not None:
		record['anchor'] = _node_summary(anchor)
	if retarget.get('applied'):
		record['hit_node'] = _node_summary(node)

	if container:
		record['container_node'] = container

	if target.children_nodes:
		child_nodes = []
		element_children = [c for c in target.children_nodes if _is_element(c)]
		for idx, child in enumerate(element_children[:3]):
			child_nodes.append(
				{
					'index': idx,
					'tag': child.tag_name,
					'attributes': {
						'id': _attrs(child).get('id'),
						'class': _attrs(child).get('class'),
					},
					'text_content': _own_text(child)[:50],
				}
			)
		if child_nodes:
			record['children_node'] = child_nodes

	return record
