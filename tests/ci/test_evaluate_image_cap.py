"""Tests for base64 image count and size caps in the evaluate action.

The evaluate action extracts inline base64 images from JavaScript results
and stores them in metadata['images']. Without caps, a page with large
data-URIs could push hundreds of KB into the next LLM request.

These tests verify the caps introduced in fix #5367:
- MAX_EVALUATE_IMAGES = 5
- MAX_IMAGE_CHARS = 200_000 (~150KB decoded)
"""

import re

import pytest

# ---------------------------------------------------------------------------
# Constants mirrored from browser_use/tools/service.py evaluate action
# ---------------------------------------------------------------------------
MAX_EVALUATE_IMAGES = 5
MAX_IMAGE_CHARS = 200_000  # ~150KB decoded


def _make_base64_image(size: int, index: int = 0) -> str:
    """Return a fake data-URI of roughly *size* characters."""
    prefix = f"data:image/png;base64,"
    # Fill with valid base64 chars to reach the target size
    payload = "A" * (size - len(prefix))
    return prefix + payload


def _apply_image_cap(result_text: str):
    """Reproduce the image-cap logic from the evaluate action.

    Returns (result_text, metadata) exactly as the production code would.
    """
    image_pattern = r"(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)"
    found_images = re.findall(image_pattern, result_text)

    metadata = None

    if found_images:
        kept = [img for img in found_images if len(img) <= MAX_IMAGE_CHARS][:MAX_EVALUATE_IMAGES]
        dropped = len(found_images) - len(kept)
        if kept:
            metadata = {"images": kept}

        # Replace image data in result text with shorter placeholder
        modified_text = result_text
        for i, img_data in enumerate(found_images, 1):
            placeholder = "[Image]"
            modified_text = modified_text.replace(img_data, placeholder)
        result_text = modified_text

        if dropped:
            result_text += "\n[" + str(dropped) + " image(s) omitted: exceeded size or count limit]"

    return result_text, metadata


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvaluateImageCap:
    """Verify image count and size caps in the evaluate action."""

    def test_images_within_limits_are_kept(self):
        """Small images that fit within both count and size limits are kept."""
        img1 = _make_base64_image(100, 1)
        img2 = _make_base64_image(200, 2)
        result_text = f"before {img1} middle {img2} after"

        text, metadata = _apply_image_cap(result_text)

        assert metadata is not None
        assert len(metadata["images"]) == 2
        assert img1 in metadata["images"]
        assert img2 in metadata["images"]
        # Placeholders replace inline data
        assert "[Image]" in text
        assert "data:image/" not in text

    def test_images_exceeding_max_chars_are_dropped(self):
        """Images larger than MAX_IMAGE_CHARS are excluded from metadata."""
        small_img = _make_base64_image(1000)
        big_img = _make_base64_image(MAX_IMAGE_CHARS + 1)
        result_text = f"{small_img} {big_img}"

        text, metadata = _apply_image_cap(result_text)

        assert metadata is not None
        assert len(metadata["images"]) == 1
        assert small_img in metadata["images"]
        assert big_img not in metadata["images"]
        # One image was dropped
        assert "1 image(s) omitted" in text

    def test_more_than_max_images_are_truncated(self):
        """Only the first MAX_EVALUATE_IMAGES qualifying images are kept."""
        images = [_make_base64_image(500, i) for i in range(8)]
        result_text = " ".join(images)

        text, metadata = _apply_image_cap(result_text)

        assert metadata is not None
        assert len(metadata["images"]) == MAX_EVALUATE_IMAGES
        # 8 - 5 = 3 dropped
        assert "3 image(s) omitted" in text

    def test_drop_count_reported_in_result_text(self):
        """The number of omitted images is accurately reported."""
        # 2 oversized + 7 small = 9 total; 5 kept, 4 dropped
        oversized = [_make_base64_image(MAX_IMAGE_CHARS + 100, i) for i in range(2)]
        small = [_make_base64_image(500, i + 10) for i in range(7)]
        result_text = " ".join(oversized + small)

        text, metadata = _apply_image_cap(result_text)

        assert metadata is not None
        assert len(metadata["images"]) == 5
        # 2 oversized dropped + 2 small over count limit = 4 dropped
        assert "4 image(s) omitted" in text
        assert "exceeded size or count limit" in text

    def test_no_images_means_metadata_is_none(self):
        """When result text has no base64 images, metadata stays None."""
        result_text = "just plain text, no images here"

        text, metadata = _apply_image_cap(result_text)

        assert metadata is None
        assert text == result_text  # unchanged
        assert "omitted" not in text

    def test_all_images_oversized_means_no_metadata(self):
        """When every image exceeds the size cap, metadata remains None."""
        big1 = _make_base64_image(MAX_IMAGE_CHARS + 500, 1)
        big2 = _make_base64_image(MAX_IMAGE_CHARS + 1000, 2)
        result_text = f"{big1} {big2}"

        text, metadata = _apply_image_cap(result_text)

        assert metadata is None
        assert "2 image(s) omitted" in text
