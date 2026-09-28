"""CDP screenshot format names are lowercase."""

import pytest

from browser_use.utils import normalize_screenshot_format


def test_uppercase_png_is_normalized():
	assert normalize_screenshot_format('PNG') == 'png'


def test_uppercase_jpeg_is_normalized():
	assert normalize_screenshot_format('JPEG') == 'jpeg'


def test_mixed_case_webp_is_normalized():
	assert normalize_screenshot_format('WebP') == 'webp'


def test_already_lowercase_is_unchanged():
	assert normalize_screenshot_format('png') == 'png'
	assert normalize_screenshot_format('jpeg') == 'jpeg'


@pytest.mark.parametrize('image_format', ['JPG', 'gif', ' bmp ', ''])
def test_unsupported_format_fails_before_capture(image_format):
	with pytest.raises(ValueError, match='Unsupported screenshot format'):
		normalize_screenshot_format(image_format)
