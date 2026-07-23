from dataclasses import dataclass

from browser_use.dom.views import SimplifiedNode

"""
Helper class for maintaining a union of rectangles (used for order of elements calculation)
"""


@dataclass(frozen=True, slots=True)
class Rect:
	"""Closed axis-aligned rectangle with (x1,y1) bottom-left, (x2,y2) top-right."""

	x1: float
	y1: float
	x2: float
	y2: float

	def __post_init__(self):
		if not (self.x1 <= self.x2 and self.y1 <= self.y2):
			return False

	# --- fast relations ----------------------------------------------------
	def area(self) -> float:
		return (self.x2 - self.x1) * (self.y2 - self.y1)

	def intersects(self, other: 'Rect') -> bool:
		return not (self.x2 <= other.x1 or other.x2 <= self.x1 or self.y2 <= other.y1 or other.y2 <= self.y1)

	def contains(self, other: 'Rect') -> bool:
		return self.x1 <= other.x1 and self.y1 <= other.y1 and self.x2 >= other.x2 and self.y2 >= other.y2


class RectUnionPure:
	"""
	Maintains a *disjoint* set of rectangles.
	No external dependencies - fine for a few thousand rectangles.

	A safety cap (_MAX_RECTS) prevents exponential explosion on pages with
	many overlapping translucent layers. Once the cap is hit, contains()
	conservatively returns False (i.e. nothing is hidden), preserving
	correctness at the cost of less aggressive paint-order filtering.
	"""

	__slots__ = ('_rects',)

	# Safety cap: with complex overlapping layers, each add() can fragment
	# existing rects into up to 4 pieces each. On heavy pages (20k+ elements)
	# this can cause exponential growth. 5000 is generous enough for normal
	# pages but prevents runaway memory/CPU.
	_MAX_RECTS = 5000

	def __init__(self):
		self._rects: list[tuple[float, float, float, float]] = []

	def _split_diff(
		self,
		ax1: float,
		ay1: float,
		ax2: float,
		ay2: float,
		bx1: float,
		by1: float,
		bx2: float,
		by2: float,
	) -> list[tuple[float, float, float, float]]:
		parts = []

		if ay1 < by1:
			parts.append((ax1, ay1, ax2, by1))
		if by2 < ay2:
			parts.append((ax1, by2, ax2, ay2))

		y_lo = max(ay1, by1)
		y_hi = min(ay2, by2)

		if ax1 < bx1:
			parts.append((ax1, y_lo, bx1, y_hi))
		if bx2 < ax2:
			parts.append((bx2, y_lo, ax2, y_hi))

		return parts

	def contains(self, r: Rect) -> bool:
		# Keep the Rect-based API for compatibility with direct helper callers.
		return self.contains_quad(r.x1, r.y1, r.x2, r.y2)

	def contains_quad(self, rx1: float, ry1: float, rx2: float, ry2: float) -> bool:
		if not self._rects:
			return False

		stack = [(rx1, ry1, rx2, ry2)]
		for sx1, sy1, sx2, sy2 in self._rects:
			new_stack = []
			for px1, py1, px2, py2 in stack:
				if sx1 <= px1 and sy1 <= py1 and sx2 >= px2 and sy2 >= py2:
					continue
				if not (px2 <= sx1 or sx2 <= px1 or py2 <= sy1 or sy2 <= py1):
					new_stack.extend(self._split_diff(px1, py1, px2, py2, sx1, sy1, sx2, sy2))
				else:
					new_stack.append((px1, py1, px2, py2))
			if not new_stack:
				return True
			stack = new_stack
		return False

	def add(self, r: Rect) -> bool:
		# Keep the Rect-based API for compatibility with direct helper callers.
		return self.add_quad(r.x1, r.y1, r.x2, r.y2)

	def add_quad(self, rx1: float, ry1: float, rx2: float, ry2: float) -> bool:
		if len(self._rects) >= self._MAX_RECTS:
			return False

		if self.contains_quad(rx1, ry1, rx2, ry2):
			return False

		pending = [(rx1, ry1, rx2, ry2)]
		for sx1, sy1, sx2, sy2 in self._rects:
			new_pending = []
			for px1, py1, px2, py2 in pending:
				if not (px2 <= sx1 or sx2 <= px1 or py2 <= sy1 or sy2 <= py1):
					new_pending.extend(self._split_diff(px1, py1, px2, py2, sx1, sy1, sx2, sy2))
				else:
					new_pending.append((px1, py1, px2, py2))
			pending = new_pending

		self._rects.extend(pending)
		return True


class PaintOrderRemover:
	"""
	Calculates which elements should be removed based on the paint order parameter.
	"""

	def __init__(self, root: SimplifiedNode):
		self.root = root

	def calculate_paint_order(self) -> None:
		nodes_info = []
		stack = [self.root]

		# Single-pass traversal to collect relevant nodes
		while stack:
			node = stack.pop()
			if node.children:
				for k in range(len(node.children) - 1, -1, -1):
					stack.append(node.children[k])

			snap = node.original_node.snapshot_node
			if snap and snap.paint_order is not None and snap.bounds:
				# Match baseline blocker detection
				is_blocker = True
				styles = snap.computed_styles
				if styles:
					bg = styles.get('background-color', 'rgba(0, 0, 0, 0)')
					if bg == 'rgba(0, 0, 0, 0)':
						is_blocker = False
					elif float(styles.get('opacity', '1')) < 0.8:
						is_blocker = False

				nodes_info.append(
					{
						'node': node,
						'po': snap.paint_order,
						'q': (
							snap.bounds.x,
							snap.bounds.y,
							snap.bounds.x + snap.bounds.width,
							snap.bounds.y + snap.bounds.height,
						),
						'is_blocker': is_blocker,
					}
				)

		# Sort by paint order descending (highest paint order on top)
		nodes_info.sort(key=lambda x: x['po'], reverse=True)

		rect_union = RectUnionPure()
		i, n = 0, len(nodes_info)

		while i < n:
			j = i
			current_po = nodes_info[i]['po']

			# 1. Check coverage for all nodes in the same paint_order group
			while j < n and nodes_info[j]['po'] == current_po:
				item = nodes_info[j]
				if rect_union.contains_quad(*item['q']):
					item['node'].ignored_by_paint_order = True
				j += 1

			# 2. Add blockers from this group to the union for subsequent groups
			for k in range(i, j):
				item = nodes_info[k]
				if item['is_blocker']:
					rect_union.add_quad(*item['q'])

			i = j

		return None
