"""Importance scoring for interactive DOM elements.

Each element in the selector_map is scored on a 0.0-1.0 scale based on
heuristic signals: tag type, viewport proximity, size, semantic richness,
accessibility role, and document position.
"""

from __future__ import annotations

from browser_use.dom.views import EnhancedDOMTreeNode


# Tag type weights (0.0 - 0.3)
_TAG_WEIGHTS: dict[str, float] = {
	'button': 0.3,
	'input': 0.3,
	'select': 0.3,
	'textarea': 0.3,
	'a': 0.25,
	'details': 0.15,
	'summary': 0.15,
}
_DEFAULT_TAG_WEIGHT = 0.1


def _tag_type_score(node: EnhancedDOMTreeNode) -> float:
	return _TAG_WEIGHTS.get(node.tag_name, _DEFAULT_TAG_WEIGHT)


def _viewport_score(node: EnhancedDOMTreeNode, viewport_height: float) -> float:
	"""Score based on proximity to viewport (0.0 - 0.2)."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return 0.0
	y = bounds.y
	if y <= viewport_height:
		return 0.2
	if y <= viewport_height + 500:
		return 0.1
	return 0.0


def _size_score(node: EnhancedDOMTreeNode, viewport_height: float) -> float:
	"""Score based on element area relative to viewport (0.0 - 0.15)."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return 0.0
	area = bounds.width * bounds.height
	# Assume viewport width ~1440 as a reasonable default
	viewport_area = 1440.0 * viewport_height
	if viewport_area <= 0:
		return 0.0
	ratio = min(area / viewport_area, 1.0)
	return ratio * 0.15


def _semantic_richness_score(node: EnhancedDOMTreeNode) -> float:
	"""Score based on presence of semantic attributes (0.0 - 0.15)."""
	score = 0.0
	attrs = node.attributes or {}
	if attrs.get('aria-label'):
		score += 0.05
	if attrs.get('placeholder'):
		score += 0.05
	text = node.get_all_children_text(max_depth=2)
	if text and len(text.strip()) > 0:
		score += 0.05
	return score


def _accessibility_role_score(node: EnhancedDOMTreeNode) -> float:
	"""Score based on ARIA role presence (0.0 - 0.1)."""
	attrs = node.attributes or {}
	if attrs.get('role'):
		return 0.1
	if node.ax_node and node.ax_node.role:
		return 0.05
	return 0.0


def _position_score(node: EnhancedDOMTreeNode, max_doc_y: float) -> float:
	"""Score based on document position — higher on page = higher score (0.0 - 0.1)."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return 0.0
	if max_doc_y <= 0:
		return 0.1
	# Linear decay: top of page = 0.1, bottom = 0.0
	return max(0.0, 0.1 * (1.0 - bounds.y / max_doc_y))


def score_element(
	node: EnhancedDOMTreeNode,
	viewport_height: float = 900,
	max_doc_y: float = 5000,
) -> float:
	"""Score a single element on a 0.0-1.0 scale."""
	total = (
		_tag_type_score(node)
		+ _viewport_score(node, viewport_height)
		+ _size_score(node, viewport_height)
		+ _semantic_richness_score(node)
		+ _accessibility_role_score(node)
		+ _position_score(node, max_doc_y)
	)
	return min(total, 1.0)


def score_elements(
	selector_map: dict[int, EnhancedDOMTreeNode],
	viewport_height: float = 900,
) -> dict[int, float]:
	"""Score all elements in selector_map, returns {backend_node_id: score}."""
	assert isinstance(selector_map, dict), 'selector_map must be a dict'

	if not selector_map:
		return {}

	# Determine max document Y for position scoring
	max_doc_y = 0.0
	for node in selector_map.values():
		bounds = node.snapshot_node.bounds if node.snapshot_node else None
		if bounds is not None:
			max_doc_y = max(max_doc_y, bounds.y)

	# Fall back to a sensible default if all elements lack bounds
	if max_doc_y <= 0:
		max_doc_y = 5000.0

	return {
		bid: score_element(node, viewport_height, max_doc_y)
		for bid, node in selector_map.items()
	}
