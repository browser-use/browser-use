"""Goal-based element scoring — boosts/penalizes elements based on task goal text."""

from __future__ import annotations

from browser_use.dom.views import EnhancedDOMTreeNode

STOPWORDS: frozenset[str] = frozenset({
	'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
	'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
	'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
	'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
	'before', 'after', 'above', 'below', 'between', 'under', 'and', 'but',
	'or', 'nor', 'not', 'so', 'yet', 'both', 'either', 'neither', 'each',
	'every', 'all', 'any', 'few', 'more', 'most', 'other', 'some', 'such',
	'no', 'only', 'same', 'than', 'too', 'very', 'just', 'because', 'if',
	'when', 'where', 'how', 'what', 'which', 'who', 'whom', 'this', 'that',
	'these', 'those', 'it', 'its', 'my', 'your', 'his', 'her', 'our',
	'their', 'me', 'him', 'us', 'them', 'i', 'you', 'he', 'she', 'we',
	'they', 'page', 'website', 'web', 'site', 'browser', 'go', 'get',
	'make', 'then', 'now', 'here', 'there',
})

_CLICK_VERBS = {'click', 'press', 'tap'}
_TYPE_VERBS = {'type', 'enter', 'fill', 'input', 'write'}


def _extract_keywords(goal: str) -> set[str]:
	"""Extract meaningful keywords from goal text."""
	words = goal.lower().split()
	return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def _element_text_fields(node: EnhancedDOMTreeNode) -> str:
	"""Concatenate all text-bearing fields of an element into a single lowercase string."""
	parts: list[str] = []
	attrs = node.attributes or {}
	for key in ('aria-label', 'placeholder', 'name', 'id', 'value', 'title'):
		val = attrs.get(key)
		if val:
			parts.append(val)
	text = node.get_all_children_text(max_depth=2)
	if text:
		parts.append(text)
	return ' '.join(parts).lower()


def apply_goal_scoring(
	scores: dict[int, float],
	selector_map: dict[int, EnhancedDOMTreeNode],
	goal: str,
) -> dict[int, float]:
	"""Modify scores in-place based on goal relevance. Returns modified scores."""
	assert isinstance(scores, dict), 'scores must be a dict'
	assert isinstance(selector_map, dict), 'selector_map must be a dict'
	assert isinstance(goal, str) and len(goal) > 0, 'goal must be a non-empty string'

	keywords = _extract_keywords(goal)
	goal_lower = goal.lower()
	goal_words = set(goal_lower.split())

	has_click_verb = bool(goal_words & _CLICK_VERBS)
	has_type_verb = bool(goal_words & _TYPE_VERBS)

	for bid, node in selector_map.items():
		if bid not in scores:
			continue

		boost = 0.0
		text_blob = _element_text_fields(node)

		# Keyword match boost
		if keywords and any(kw in text_blob for kw in keywords):
			boost += 0.15

		# Action-type boosts
		tag = node.tag_name
		if has_click_verb and tag in ('button', 'a'):
			boost += 0.1
		if has_type_verb and tag in ('input', 'textarea'):
			boost += 0.1

		if boost > 0:
			scores[bid] = min(scores[bid] + boost, 1.0)

	return scores
