"""Regression tests for _add_overlay_to_image GIF overlay rendering."""

from PIL import Image, ImageFont

from browser_use.agent.gif import _add_overlay_to_image


def _make_image() -> Image.Image:
	return Image.new('RGB', (640, 480), (255, 255, 255))


def test_overlay_with_display_step_true():
	"""The step badge and goal text render normally with display_step=True."""
	font = ImageFont.load_default()
	result = _add_overlay_to_image(
		image=_make_image(),
		step_number=3,
		goal_text='Click the submit button',
		regular_font=font,
		title_font=font,
		margin=20,
		display_step=True,
	)
	assert result.size == (640, 480)
	assert result.mode == 'RGB'


def test_overlay_with_display_step_false():
	"""display_step=False must not raise UnboundLocalError (regression for #5801)."""
	font = ImageFont.load_default()
	result = _add_overlay_to_image(
		image=_make_image(),
		step_number=3,
		goal_text='Goal text renders even without the step badge',
		regular_font=font,
		title_font=font,
		margin=20,
		display_step=False,
	)
	assert result.size == (640, 480)
	assert result.mode == 'RGB'
