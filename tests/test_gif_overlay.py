import pytest
from PIL import Image, ImageFont

# Import the private helper directly – it is part of the public contract of the
# module even though it is prefixed with an underscore.
from browser_use.agent.gif import _add_overlay_to_image


@pytest.fixture
def dummy_image():
    """Create a plain RGB image for overlay tests."""
    return Image.new("RGB", (800, 600), (10, 10, 10))


@pytest.fixture
def default_font():
    """Return a deterministic font – the built‑in default works everywhere."""
    return ImageFont.load_default()


def test_overlay_with_step(dummy_image, default_font):
    """Calling with the default ``display_step=True`` must succeed."""
    img = _add_overlay_to_image(
        dummy_image,
        step=1,
        goal_text="Test Goal",
        step_font=default_font,
        goal_font=default_font,
        font_size=40,
        overlay_color=None,
        display_step=True,
    )
    # The function returns the same Image object (mutated in‑place).
    assert isinstance(img, Image.Image)
    # Basic sanity: the image size should stay unchanged.
    assert img.size == (800, 600)


def test_overlay_without_step(dummy_image, default_font):
    """Calling with ``display_step=False`` must not raise and must draw the goal."""
    img = _add_overlay_to_image(
        dummy_image,
        step=1,
        goal_text="Goal Only",
        step_font=default_font,
        goal_font=default_font,
        font_size=40,
        overlay_color=None,
        display_step=False,
    )
    assert isinstance(img, Image.Image)
    assert img.size == (800, 600)

    # Verify that the goal text area has been altered (i.e., not the original colour).
    # Sample a pixel near the centre where the goal overlay is expected.
    centre_pixel = img.getpixel((400, 500))  # bottom‑center region
    # The original background is (10, 10, 10). The overlay uses a semi‑transparent
    # white background which after compositing results in a lighter colour.
    assert centre_pixel != (10, 10, 10)
