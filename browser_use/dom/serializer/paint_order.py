from collections import defaultdict
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
	"""

	__slots__ = ('_rects',)

	def __init__(self):
		self._rects: list[Rect] = []

	# -----------------------------------------------------------------
	def _split_diff(self, a: Rect, b: Rect) -> list[Rect]:
		r"""
		Return list of up to 4 rectangles = a \ b.
		Assumes a intersects b.
		"""
		parts = []

		# Bottom slice
		if a.y1 < b.y1:
			parts.append(Rect(a.x1, a.y1, a.x2, b.y1))
		# Top slice
		if b.y2 < a.y2:
			parts.append(Rect(a.x1, b.y2, a.x2, a.y2))

		# Middle (vertical) strip: y overlap is [max(a.y1,b.y1), min(a.y2,b.y2)]
		y_lo = max(a.y1, b.y1)
		y_hi = min(a.y2, b.y2)

		# Left slice
		if a.x1 < b.x1:
			parts.append(Rect(a.x1, y_lo, b.x1, y_hi))
		# Right slice
		if b.x2 < a.x2:
			parts.append(Rect(b.x2, y_lo, a.x2, y_hi))

		return parts

	# -----------------------------------------------------------------
	def contains(self, r: Rect) -> bool:
		"""
		True iff r is fully covered by the current union.
		"""
		if not self._rects:
			return False

		stack = [r]
		for s in self._rects:
			new_stack = []
			for piece in stack:
				if s.contains(piece):
					# piece completely gone
					continue
				if piece.intersects(s):
					new_stack.extend(self._split_diff(piece, s))
				else:
					new_stack.append(piece)
			if not new_stack:  # everything eaten – covered
				return True
			stack = new_stack
		return False  # something survived

	# -----------------------------------------------------------------
	def add(self, r: Rect) -> bool:
		"""
		Insert r unless it is already covered.
		Returns True if the union grew.
		"""
		if self.contains(r):
			return False

		pending = [r]
		i = 0
		while i < len(self._rects):
			s = self._rects[i]
			new_pending = []
			changed = False
			for piece in pending:
				if piece.intersects(s):
					new_pending.extend(self._split_diff(piece, s))
					changed = True
				else:
					new_pending.append(piece)
			pending = new_pending
			if changed:
				# s unchanged; proceed with next existing rectangle
				i += 1
			else:
				i += 1

		# Any left‑over pieces are new, non‑overlapping areas
		self._rects.extend(pending)
		return True


class PaintOrderRemover:
	"""
	Calculates which elements should be removed based on the paint order parameter.
	"""

	def __init__(self, root: SimplifiedNode):
		self.root = root

	def calculate_paint_order(self) -> None:
		all_simplified_nodes_with_paint_order: list[SimplifiedNode] = []

		def collect_paint_order(node: SimplifiedNode) -> None:
			if (
				node.original_node.snapshot_node
				and node.original_node.snapshot_node.paint_order is not None
				and node.original_node.snapshot_node.bounds is not None
			):
				all_simplified_nodes_with_paint_order.append(node)

			for child in node.children:
				collect_paint_order(child)

		collect_paint_order(self.root)

		grouped_by_paint_order: defaultdict[int, list[SimplifiedNode]] = defaultdict(list)

		for node in all_simplified_nodes_with_paint_order:
			if node.original_node.snapshot_node and node.original_node.snapshot_node.paint_order is not None:
				grouped_by_paint_order[node.original_node.snapshot_node.paint_order].append(node)

		rect_union = RectUnionPure()

		for paint_order, nodes in sorted(grouped_by_paint_order.items(), key=lambda x: -x[0]):
			rects_to_add = []

			for node in nodes:
				if not node.original_node.snapshot_node or not node.original_node.snapshot_node.bounds:
					continue  # shouldn't happen by how we filter them out in the first place

				rect = Rect(
					x1=node.original_node.snapshot_node.bounds.x,
					y1=node.original_node.snapshot_node.bounds.y,
					x2=node.original_node.snapshot_node.bounds.x + node.original_node.snapshot_node.bounds.width,
					y2=node.original_node.snapshot_node.bounds.y + node.original_node.snapshot_node.bounds.height,
				)

				if rect_union.contains(rect):
					node.ignored_by_paint_order = True

				# don't add to the nodes if opacity is less then 0.95 or background-color is transparent
				if (
					node.original_node.snapshot_node.computed_styles
					and node.original_node.snapshot_node.computed_styles.get('background-color', 'rgba(0, 0, 0, 0)')
					== 'rgba(0, 0, 0, 0)'
				) or (
					node.original_node.snapshot_node.computed_styles
					and float(node.original_node.snapshot_node.computed_styles.get('opacity', '1'))
					< 0.8  # this is highly vibes based number
				):
					continue

				rects_to_add.append(rect)

			for rect in rects_to_add:
				rect_union.add(rect)

		return None
