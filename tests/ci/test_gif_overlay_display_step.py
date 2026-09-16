"""Regression test for https://github.com/browser-use/browser-use/issues/5801.

_add_overlay_to_image crashed with UnboundLocalError when display_step=False
because y_step/padding were only assigned inside the `if display_step:` block.
"""

from PIL import Image, ImageChops, ImageFont

from browser_use.agent.gif import _add_overlay_to_image


def _image_and_font():
	return Image.new('RGB', (800, 600), (10, 10, 10)), ImageFont.load_default()


def _render(display_step: bool):
	image, font = _image_and_font()
	result = _add_overlay_to_image(image, 1, 'hello goal', font, font, 40, None, display_step=display_step)  # type: ignore
	return image, result


def _overlay_bbox(image: Image.Image, result: Image.Image) -> tuple[int, int, int, int]:
	"""Bounding box of everything the overlay drew, with an assert that it drew something."""
	bbox = ImageChops.difference(image, result).getbbox()
	assert bbox is not None, 'the overlay drew nothing at all'
	return bbox


def test_overlay_without_step_badge_renders_goal():
	image, result = _render(display_step=False)
	assert result.size == (800, 600)
	assert result.mode == 'RGB'

	x0, y0, x1, y1 = _overlay_bbox(image, result)
	# The goal band sits in the lower half, fully inside the frame, and centred
	# horizontally: an unanchored y_step would move it, clip it or drop it.
	assert y0 >= result.height // 2, (x0, y0, x1, y1)
	assert 0 < x0 and x1 < result.width, (x0, y0, x1, y1)
	assert 0 < y0 and y1 < result.height, (x0, y0, x1, y1)
	assert abs(x0 + x1 - result.width) <= 2, (x0, y0, x1, y1)

	# Glyphs, not only the background box: white text on a black box, drawn over
	# a (10, 10, 10) frame, so a light pixel can only come from the goal text.
	pixels = result.crop((x0, y0, x1, y1)).getdata()
	assert any(all(channel >= 150 for channel in rgb) for rgb in pixels), 'no goal glyphs rendered'


def test_overlay_with_step_badge_still_renders():
	image, result = _render(display_step=True)
	assert result.size == (800, 600)
	assert result.mode == 'RGB'

	x0, y0, x1, y1 = _overlay_bbox(image, result)
	assert 0 < x0 and x1 < result.width and 0 < y0 and y1 < result.height, (x0, y0, x1, y1)
	# The step badge is anchored bottom-left, so the drawn region reaches further
	# left than the goal band alone.
	assert x0 < 100, (x0, y0, x1, y1)
	pixels = result.crop((x0, y0, x1, y1)).getdata()
	assert any(all(channel >= 150 for channel in rgb) for rgb in pixels), 'no glyphs rendered'


def test_overlay_without_step_badge_is_anchored_no_higher_than_with_one():
	"""The else-branch re-anchors with zero step height instead of a stale anchor."""
	baseline_image, baseline = _render(display_step=True)
	off_image, off = _render(display_step=False)
	assert _overlay_bbox(baseline_image, baseline)[1] <= _overlay_bbox(off_image, off)[1]
