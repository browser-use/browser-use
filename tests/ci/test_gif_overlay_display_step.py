from PIL import Image, ImageFont

from browser_use.agent.gif import _add_overlay_to_image


def _make_image(width: int = 800, height: int = 600) -> Image.Image:
	return Image.new('RGB', (width, height), (255, 255, 255))


def test_add_overlay_display_step_false() -> None:
	"""Overlay with display_step=False must not crash (goal-only overlay)."""
	font = ImageFont.load_default()
	result = _add_overlay_to_image(
		image=_make_image(),
		step_number=1,
		goal_text='goal',
		regular_font=font,  # type: ignore[arg-type]
		title_font=font,  # type: ignore[arg-type]
		margin=40,
		display_step=False,
	)
	assert isinstance(result, Image.Image)
	assert result.size == (800, 600)


def test_add_overlay_display_step_true() -> None:
	"""Guard: default display_step=True overlay keeps working."""
	font = ImageFont.load_default()
	result = _add_overlay_to_image(
		image=_make_image(),
		step_number=1,
		goal_text='goal',
		regular_font=font,  # type: ignore[arg-type]
		title_font=font,  # type: ignore[arg-type]
		margin=40,
		display_step=True,
	)
	assert isinstance(result, Image.Image)
	assert result.size == (800, 600)
