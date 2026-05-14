"""Self-Healing Element Recovery Engine.

When an element lookup fails (e.g., page changed after a navigation or dynamic update),
this module attempts to re-find the element using multiple recovery strategies:

1. Text content match — find element with same visible text
2. Accessibility label match — aria-label, placeholder, title, alt
3. Attribute fingerprint — similar class, role, data-* attributes
4. Structural position — same nth-child path in DOM
5. Tag + role fallback — same tag type in similar context

Usage:
    healer = AutoHealEngine()
    # Before click: fingerprint the element
    healer.fingerprint(index, node)
    # After failure: attempt recovery
    recovered = await healer.try_heal(index, cdp_session)
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger('browser_use.dom.auto_heal')


@dataclass
class ElementFingerprint:
	"""Captured state of a DOM element for later recovery."""

	index: int
	tag: str
	text: str
	aria_label: str
	placeholder: str
	title: str
	alt: str
	role: str
	classes: list[str]
	data_attrs: dict[str, str]
	# Structural position
	parent_tag: str
	sibling_index: int
	# For observability
	healed_count: int = 0
	last_healed_via: str = ''


@dataclass
class HealResult:
	"""Result of a healing attempt."""

	healed: bool
	new_backend_node_id: int | None = None
	strategy: str = ''
	confidence: float = 0.0
	details: str = ''


class AutoHealEngine:
	"""Self-healing element recovery engine.

	Maintains fingerprints of recently interacted elements and attempts
	automatic recovery when element lookups fail.
	"""

	# JS to fingerprint an element by backend node id
	_FINGERPRINT_JS = """
	(nodeId) => {
		const node = document.querySelector(`[data-backend-node-id="${nodeId}"]`)
			|| (() => {
				// Fallback: try to find by walking the tree
				const walker = document.createTreeWalker(
					document.body, NodeFilter.SHOW_ELEMENT
				);
				while (walker.nextNode()) {
					if (walker.currentNode.backendNodeId === nodeId) return walker.currentNode;
				}
				return null;
			})();

		if (!node) return null;

		const text = (node.innerText || node.textContent || '').trim().substring(0, 200);
		const tag = node.tagName.toLowerCase();
		const attrs = {};
		for (const a of node.attributes || []) {
			if (['style'].includes(a.name)) continue;
			attrs[a.name] = a.value.substring(0, 200);
		}
		const classes = Array.from(node.classList || []).sort();
		const dataAttrs = {};
		for (const [k, v] of Object.entries(attrs)) {
			if (k.startsWith('data-')) dataAttrs[k] = v;
		}

		const parent = node.parentElement;
		const siblings = parent ? Array.from(parent.children) : [];
		const siblingIndex = siblings.indexOf(node);

		return {
			tag,
			text,
			ariaLabel: attrs['aria-label'] || '',
			placeholder: attrs['placeholder'] || '',
			title: attrs['title'] || '',
			alt: attrs['alt'] || '',
			role: attrs['role'] || '',
			classes,
			dataAttrs,
			parentTag: parent ? parent.tagName.toLowerCase() : '',
			siblingIndex,
			attrs,
		};
	}
	"""

	# JS to find element by text content
	_FIND_BY_TEXT_JS = """
	(text, tagHint) => {
		if (!text) return null;
		const lower = text.toLowerCase().trim();

		// Strategy 1: Exact text match
		const allElements = document.querySelectorAll(
			tagHint || '*'
		);
		for (const el of allElements) {
			const elText = (el.innerText || el.textContent || '').trim().toLowerCase();
			if (elText === lower && el.offsetParent !== null) {
				return { backendNodeId: el.backendNodeId || null, strategy: 'exact_text', el };
			}
		}

		// Strategy 2: Partial text match
		for (const el of allElements) {
			const elText = (el.innerText || el.textContent || '').trim().toLowerCase();
			if (elText.includes(lower) && elText.length < lower.length * 3 && el.offsetParent !== null) {
				return { backendNodeId: el.backendNodeId || null, strategy: 'partial_text', el };
			}
		}

		return null;
	}
	"""

	# JS to find element by accessibility attributes
	_FIND_BY_A11Y_JS = """
	(ariaLabel, placeholder, title, alt) => {
		const selectors = [];
		if (ariaLabel) selectors.push(`[aria-label="${ariaLabel}"]`);
		if (placeholder) selectors.push(`[placeholder="${placeholder}"]`);
		if (title) selectors.push(`[title="${title}"]`);
		if (alt) selectors.push(`[alt="${alt}"]`);

		for (const sel of selectors) {
			try {
				const el = document.querySelector(sel);
				if (el && el.offsetParent !== null) {
					return { backendNodeId: el.backendNodeId || null, strategy: 'a11y_attr', el };
				}
			} catch(e) {}
		}
		return null;
	}
	"""

	# JS to find element by role and structural similarity
	_FIND_BY_ROLE_JS = """
	(role, tag, parentTag, siblingIndex) => {
		let candidates = [];

		if (role) {
			candidates = document.querySelectorAll(`[role="${role}"]`);
		} else if (tag) {
			candidates = document.querySelectorAll(tag);
		}

		if (candidates.length === 0) return null;

		// If only one candidate, use it
		if (candidates.length === 1 && candidates[0].offsetParent !== null) {
			return { backendNodeId: candidates[0].backendNodeId || null, strategy: 'single_role', el: candidates[0] };
		}

		// Multiple candidates: prefer one with matching parent tag and sibling position
		for (const el of candidates) {
			if (el.offsetParent === null) continue;
			const parent = el.parentElement;
			if (parent && parent.tagName.toLowerCase() === parentTag) {
				const siblings = Array.from(parent.children);
				const idx = siblings.indexOf(el);
				if (Math.abs(idx - siblingIndex) <= 1) {
					return { backendNodeId: el.backendNodeId || null, strategy: 'structural_position', el };
				}
			}
		}

		// Fallback: first visible candidate
		for (const el of candidates) {
			if (el.offsetParent !== null) {
				return { backendNodeId: el.backendNodeId || null, strategy: 'role_fallback', el };
			}
		}

		return null;
	}
	"""

	def __init__(self, max_fingerprints: int = 200):
		self._fingerprints: dict[int, ElementFingerprint] = {}
		self._max_fingerprints = max_fingerprints
		self._heal_stats = {'attempts': 0, 'successes': 0, 'failures': 0}

	def fingerprint(self, index: int, node: Any) -> None:
		"""Store a fingerprint for an element before interaction.

		Call this BEFORE clicking/filling so we have a reference
		if the element disappears.

		Args:
			index: The element index from the selector map.
			node: The EnhancedDOMTreeNode from browser-use.
		"""
		if len(self._fingerprints) >= self._max_fingerprints:
			# Evict oldest entry
			oldest_key = next(iter(self._fingerprints))
			del self._fingerprints[oldest_key]

		# Extract info from the node
		text = ''
		aria_label = ''
		placeholder = ''
		title = ''
		alt = ''
		role = ''
		classes = []
		data_attrs = {}
		tag = ''
		parent_tag = ''
		sibling_index = 0

		if hasattr(node, 'ax_node') and node.ax_node:
			text = (node.ax_node.name or '').strip()[:200]
			role = node.ax_node.role or ''

		if hasattr(node, 'tag_name'):
			tag = (node.tag_name or '').lower()

		if hasattr(node, 'attributes') and node.attributes:
			for key, val in node.attributes.items():
				if key == 'aria-label':
					aria_label = val
				elif key == 'placeholder':
					placeholder = val
				elif key == 'title':
					title = val
				elif key == 'alt':
					alt = val
				elif key == 'role':
					role = val
				elif key == 'class':
					classes = sorted(val.split())
				elif key.startswith('data-'):
					data_attrs[key] = val

		self._fingerprints[index] = ElementFingerprint(
			index=index,
			tag=tag,
			text=text,
			aria_label=aria_label,
			placeholder=placeholder,
			title=title,
			alt=alt,
			role=role,
			classes=classes,
			data_attrs=data_attrs,
			parent_tag=parent_tag,
			sibling_index=sibling_index,
		)

		logger.debug(f'🔒 Fingerprinted element {index}: tag={tag}, text={text[:50]!r}, role={role}')

	async def try_heal(
		self,
		index: int,
		cdp_session: Any,
	) -> HealResult:
		"""Attempt to recover a lost element.

		Args:
			index: The element index that failed lookup.
			cdp_session: The CDP session from browser_session.get_or_create_cdp_session().

		Returns:
			HealResult with success status and new backend node ID if found.
		"""
		self._heal_stats['attempts'] += 1

		fp = self._fingerprints.get(index)
		if not fp:
			self._heal_stats['failures'] += 1
			return HealResult(healed=False, details='No fingerprint available')

		# Try each recovery strategy in order
		strategies = [
			('text_match', self._heal_by_text, (fp, cdp_session)),
			('a11y_match', self._heal_by_a11y, (fp, cdp_session)),
			('role_match', self._heal_by_role, (fp, cdp_session)),
		]

		for strategy_name, strategy_fn, args in strategies:
			try:
				result = await strategy_fn(*args)
				if result and result.get('backendNodeId'):
					fp.healed_count += 1
					fp.last_healed_via = strategy_name
					self._heal_stats['successes'] += 1
					logger.info(f'🩹 Healed element {index} via {strategy_name} (text={fp.text[:30]!r}, heal #{fp.healed_count})')
					return HealResult(
						healed=True,
						new_backend_node_id=result['backendNodeId'],
						strategy=strategy_name,
						confidence=0.8 if strategy_name == 'text_match' else 0.6,
						details=f'Found via {strategy_name}',
					)
			except Exception as e:
				logger.debug(f'Heal strategy {strategy_name} failed for element {index}: {e}')
				continue

		self._heal_stats['failures'] += 1
		logger.info(f'❌ Could not heal element {index} (tag={fp.tag}, text={fp.text[:30]!r}) — all strategies exhausted')
		return HealResult(healed=False, details='All recovery strategies failed')

	async def _heal_by_text(self, fp: ElementFingerprint, cdp_session: Any) -> dict | None:
		"""Recovery strategy 1: Find by visible text content."""
		if not fp.text:
			return None

		tag_hint = fp.tag if fp.tag in ('button', 'a', 'input', 'select', 'textarea') else None
		expression = f'({self._FIND_BY_TEXT_JS.strip()})({json.dumps(fp.text)}, {json.dumps(tag_hint)})'
		resp = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': expression}, session_id=cdp_session.session_id
		)
		return resp.get('result', {}).get('value') if resp else None

	async def _heal_by_a11y(self, fp: ElementFingerprint, cdp_session: Any) -> dict | None:
		"""Recovery strategy 2: Find by accessibility attributes."""
		if not any([fp.aria_label, fp.placeholder, fp.title, fp.alt]):
			return None

		expression = f'({self._FIND_BY_A11Y_JS.strip()})({json.dumps(fp.aria_label)}, {json.dumps(fp.placeholder)}, {json.dumps(fp.title)}, {json.dumps(fp.alt)})'
		resp = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': expression}, session_id=cdp_session.session_id
		)
		return resp.get('result', {}).get('value') if resp else None

	async def _heal_by_role(self, fp: ElementFingerprint, cdp_session: Any) -> dict | None:
		"""Recovery strategy 3: Find by role/tag and structural position."""
		if not fp.role and not fp.tag:
			return None

		expression = f'({self._FIND_BY_ROLE_JS.strip()})({json.dumps(fp.role)}, {json.dumps(fp.tag)}, {json.dumps(fp.parent_tag)}, {fp.sibling_index})'
		resp = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': expression}, session_id=cdp_session.session_id
		)
		return resp.get('result', {}).get('value') if resp else None

	def get_stats(self) -> dict:
		"""Return healing statistics for observability."""
		return {
			**self._heal_stats,
			'fingerprints_stored': len(self._fingerprints),
			'success_rate': (
				self._heal_stats['successes'] / self._heal_stats['attempts'] if self._heal_stats['attempts'] > 0 else 0.0
			),
		}

	def clear(self) -> None:
		"""Clear all fingerprints and stats."""
		self._fingerprints.clear()
		self._heal_stats = {'attempts': 0, 'successes': 0, 'failures': 0}
