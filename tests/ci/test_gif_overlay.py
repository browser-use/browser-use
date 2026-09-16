"""Tests for GIF overlay generation."""

import typing

from PIL import Image, ImageFont

from browser_use.agent.gif import _add_overlay_to_image


def test_add_overlay_display_step_true() -> None:
	"""Test overlay addition when display_step is True."""
	base_image = Image.new('RGB', (800, 600), color=(50, 100, 150))
	font = typing.cast(ImageFont.FreeTypeFont, ImageFont.load_default())
	result = _add_overlay_to_image(
		image=base_image,
		step_number=1,
		goal_text='Test Goal Description',
		regular_font=font,
		title_font=font,
		margin=20,
		display_step=True,
	)
	assert isinstance(result, Image.Image)
	assert result.size == (800, 600)


def test_add_overlay_display_step_false_no_unbound_local_error() -> None:
	"""Test overlay addition when display_step is False to ensure no UnboundLocalError occurs."""
	base_image = Image.new('RGB', (800, 600), color=(50, 100, 150))
	font = typing.cast(ImageFont.FreeTypeFont, ImageFont.load_default())
	result = _add_overlay_to_image(
		image=base_image,
		step_number=1,
		goal_text='Test Goal Description with display_step=False',
		regular_font=font,
		title_font=font,
		margin=20,
		display_step=False,
	)
	assert isinstance(result, Image.Image)
	assert result.size == (800, 600)

