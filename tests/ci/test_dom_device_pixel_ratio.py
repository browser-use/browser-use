from browser_use.dom.service import DomService


def test_resolve_device_pixel_ratio_prefers_cdp_metrics_when_available():
	ratio = DomService._resolve_device_pixel_ratio(
		metrics_ratio=2.0,
		js_device_pixel_ratio=1.0,
		js_visual_viewport_scale=1.0,
		js_screen_to_inner_width_ratio=1.0,
	)
	assert ratio == 2.0


def test_resolve_device_pixel_ratio_uses_js_fallback_when_metrics_is_one():
	ratio = DomService._resolve_device_pixel_ratio(
		metrics_ratio=1.0,
		js_device_pixel_ratio=1.0,
		js_visual_viewport_scale=2.0,
		js_screen_to_inner_width_ratio=1.33,
	)
	assert ratio == 2.0


def test_resolve_device_pixel_ratio_returns_one_when_no_valid_fallback():
	ratio = DomService._resolve_device_pixel_ratio(
		metrics_ratio=1.0,
		js_device_pixel_ratio=None,
		js_visual_viewport_scale=-5,
		js_screen_to_inner_width_ratio=99,
	)
	assert ratio == 1.0


def test_resolve_device_pixel_ratio_ignores_invalid_values():
	ratio = DomService._resolve_device_pixel_ratio(
		metrics_ratio='invalid',
		js_device_pixel_ratio=None,
		js_visual_viewport_scale=-5,
		js_screen_to_inner_width_ratio=99,
	)
	assert ratio == 1.0

