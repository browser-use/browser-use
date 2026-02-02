import base64
import io

import pytest
from PIL import Image

from browser_use.browser.python_highlights import create_highlighted_screenshot
from browser_use.dom.views import DOMRect


class StubElement:
    def __init__(self):
        self.absolute_position = DOMRect(x=5, y=5, width=10, height=10)
        self.tag_name = "button"
        self.attributes = {"type": "button"}
        self.backend_node_id = 1

    def get_meaningful_text_for_llm(self) -> str:
        return ""


@pytest.mark.asyncio
async def test_create_highlighted_screenshot_draws_box():
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    result = await create_highlighted_screenshot(
        b64,
        {1: StubElement()},
        device_pixel_ratio=1.0,
        viewport_offset_x=0,
        viewport_offset_y=0,
        filter_highlight_ids=False,
    )
    decoded = base64.b64decode(result)
    out = Image.open(io.BytesIO(decoded)).convert("RGBA")
    pixel = out.getpixel((5, 5))
    assert pixel[:3] != (255, 255, 255)
