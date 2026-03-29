"""Dominant group detection — finds the main repeated content group.

Identifies lists of similar elements (search results, product cards, table rows)
by looking for siblings with matching (tag, role) under a common parent.
"""

from __future__ import annotations

from dataclasses import dataclass

from browser_use.dom.views import EnhancedDOMTreeNode


@dataclass
class DominantGroup:
	element_ids: list[int]  # backend_node_ids in document order
	group_tag: str  # common tag
	group_role: str | None  # common role if any
	container_backend_node_id: int | None  # parent container if found


def _get_role(node: EnhancedDOMTreeNode) -> str | None:
	"""Extract role from attributes or AX node."""
	role = (node.attributes or {}).get('role')
	if role:
		return role
	if node.ax_node and node.ax_node.role:
		return node.ax_node.role
	return None


def _bounds_size_variance(nodes: list[EnhancedDOMTreeNode]) -> float:
	"""Compute variance of bounding-box areas across nodes. Lower = more uniform."""
	areas: list[float] = []
	for n in nodes:
		bounds = n.snapshot_node.bounds if n.snapshot_node else None
		if bounds is not None:
			areas.append(bounds.width * bounds.height)
	if len(areas) < 2:
		return 0.0
	mean = sum(areas) / len(areas)
	return sum((a - mean) ** 2 for a in areas) / len(areas)


def _sort_key(node: EnhancedDOMTreeNode) -> tuple[float, float]:
	"""Document order: (bounds.y, bounds.x), defaulting to inf for missing bounds."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return (float('inf'), float('inf'))
	return (bounds.y, bounds.x)


def detect_dominant_group(
	selector_map: dict[int, EnhancedDOMTreeNode],
) -> DominantGroup | None:
	"""Detect the dominant content group from the selector map.

	Algorithm:
	1. Group interactive elements by parent backend_node_id.
	2. Within each parent group, sub-group by (tag, role).
	3. Largest sub-group with >= 3 members wins.
	4. Ties broken by lowest bounding-box size variance.
	5. Elements ordered by document position.
	"""
	assert isinstance(selector_map, dict), 'selector_map must be a dict'

	if len(selector_map) < 3:
		return None

	# Group by parent
	parent_groups: dict[int, list[EnhancedDOMTreeNode]] = {}
	for node in selector_map.values():
		parent = node.parent_node
		if parent is None:
			continue
		pid = parent.backend_node_id
		parent_groups.setdefault(pid, []).append(node)

	# Find best (tag, role) sub-group across all parents
	best_group: list[EnhancedDOMTreeNode] | None = None
	best_tag: str = ''
	best_role: str | None = None
	best_parent_id: int | None = None
	best_variance: float = float('inf')

	for pid, children in parent_groups.items():
		# Sub-group by (tag, role)
		sub: dict[tuple[str, str | None], list[EnhancedDOMTreeNode]] = {}
		for child in children:
			key = (child.tag_name, _get_role(child))
			sub.setdefault(key, []).append(child)

		for (tag, role), members in sub.items():
			if len(members) < 3:
				continue

			# Check if this group is better than current best
			is_larger = best_group is None or len(members) > len(best_group)
			if is_larger:
				best_group = members
				best_tag = tag
				best_role = role
				best_parent_id = pid
				best_variance = _bounds_size_variance(members)
			elif best_group is not None and len(members) == len(best_group):
				# Tie-break: prefer lower bounding box size variance
				var = _bounds_size_variance(members)
				if var < best_variance:
					best_group = members
					best_tag = tag
					best_role = role
					best_parent_id = pid
					best_variance = var

	if best_group is None:
		return None

	# Sort by document position
	best_group.sort(key=_sort_key)

	return DominantGroup(
		element_ids=[n.backend_node_id for n in best_group],
		group_tag=best_tag,
		group_role=best_role,
		container_backend_node_id=best_parent_id,
	)
