"""Tests for DOM highlight badge placement."""

from browser_use.browser.python_highlights import get_index_overlay_box


def boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int], margin: int = 4) -> bool:
	"""Return True when two rectangles overlap or visually crowd each other."""
	return not (a[2] + margin <= b[0] or b[2] + margin <= a[0] or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def test_get_index_overlay_box_avoids_colliding_badges_for_dense_small_elements() -> None:
	"""Closely packed image-only targets should get readable, non-overlapping index badges."""
	image_size = (200, 120)
	overlay_size = (34, 18)
	element_boxes = [
		(20, 12, 42, 34),
		(48, 12, 70, 34),
		(76, 12, 98, 34),
	]

	occupied: list[tuple[int, int, int, int]] = []
	for element_box in element_boxes:
		badge_box = get_index_overlay_box(element_box, overlay_size, image_size, occupied)
		assert 0 <= badge_box[0] < badge_box[2] <= image_size[0]
		assert 0 <= badge_box[1] < badge_box[3] <= image_size[1]
		assert all(not boxes_overlap(badge_box, other) for other in occupied)
		occupied.append(badge_box)

	assert len(occupied) == 3


def test_get_index_overlay_box_stays_within_screenshot_bounds() -> None:
	"""Badge placement should remain visible even for elements on the screenshot edge."""
	image_size = (120, 80)
	overlay_size = (40, 20)
	element_box = (96, 4, 118, 24)

	badge_box = get_index_overlay_box(element_box, overlay_size, image_size)

	assert 0 <= badge_box[0] < badge_box[2] <= image_size[0]
	assert 0 <= badge_box[1] < badge_box[3] <= image_size[1]
