"""Test Mouse.scroll's anchor-point resolution honors explicit x=0/y=0 (see actor/mouse.py)."""

from browser_use.actor.mouse import _resolve_scroll_anchor


def test_explicit_zero_x_is_honored_as_left_edge():
	scroll_x, scroll_y = _resolve_scroll_anchor(x=0, y=100, viewport_width=1000, viewport_height=800)
	assert scroll_x == 0
	assert scroll_y == 100


def test_explicit_zero_y_is_honored_as_top_edge():
	scroll_x, scroll_y = _resolve_scroll_anchor(x=100, y=0, viewport_width=1000, viewport_height=800)
	assert scroll_x == 100
	assert scroll_y == 0


def test_both_unset_falls_back_to_viewport_center():
	scroll_x, scroll_y = _resolve_scroll_anchor(x=None, y=None, viewport_width=1000, viewport_height=800)
	assert scroll_x == 500
	assert scroll_y == 400


def test_positive_coordinates_are_passed_through():
	scroll_x, scroll_y = _resolve_scroll_anchor(x=42, y=99, viewport_width=1000, viewport_height=800)
	assert scroll_x == 42
	assert scroll_y == 99
