"""Regression test for https://github.com/browser-use/browser-use/issues/5801.

_add_overlay_to_image crashed with UnboundLocalError when display_step=False
because y_step/padding were only assigned inside the `if display_step:` block.
"""

from PIL import Image, ImageFont

from browser_use.agent.gif import _add_overlay_to_image


def _image_and_font():
	return Image.new('RGB', (800, 600), (10, 10, 10)), ImageFont.load_default()


def test_overlay_without_step_badge_renders_goal():
	image, font = _image_and_font()
	result = _add_overlay_to_image(image, 1, 'hello goal', font, font, 40, None, display_step=False)
	assert result.size == (800, 600)
	assert result.mode == 'RGB'


def test_overlay_with_step_badge_still_renders():
	image, font = _image_and_font()
	result = _add_overlay_to_image(image, 1, 'hello goal', font, font, 40, None, display_step=True)
	assert result.size == (800, 600)
	assert result.mode == 'RGB'
