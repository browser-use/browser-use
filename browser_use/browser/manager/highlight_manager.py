from PIL import Image, ImageDraw, ImageFont

from browser_use.dom.history_tree_processor.view import DOMHistoryElement


class HighlightManager:
    def highlight_element(self, interacted_element: list[DOMHistoryElement | None] | list[None], image: Image.Image):
        for element in interacted_element:
            if element:
                self._create_highlight_element(element, image)

    def _create_highlight_element(self, element: DOMHistoryElement, image: Image.Image):
        index = element.highlight_index
        base_color, background_color = self._generate_color(index)
        position = element.position

        if not position:
            raise ValueError("Position is required to highlight an element")
        
        draw = ImageDraw.Draw(image, "RGBA")
        # Draw the outline with a light transparent color filling
        draw.rectangle(
            [position.left, position.top, position.left + position.width, position.top + position.height],
            outline=base_color,
            fill=background_color
        )

        # Draw the label
        font = ImageFont.load_default()
        label_text = str(index)
        label_bbox = draw.textbbox((0, 0), label_text, font=font)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]

        label_top = position.top + 2
        label_left = position.left + position.width - label_width - 2

        if position.width < label_width + 4 or position.height < label_height + 4:
            label_top = position.top - label_height - 2
            label_left = position.left + position.width - label_width

        # Draw the label background
        draw.rectangle(
            [label_left, label_top, label_left + label_width, label_top + label_height],
            fill=base_color,
            outline=base_color
        )
        # Draw the label text
        draw.text((label_left, label_top), label_text, fill="white", font=font)

    def _generate_color(self, index):
        colors = [
            '#FF0000', '#00FF00', '#0000FF', '#FFA500',
            '#800080', '#008080', '#FF69B4', '#4B0082',
            '#FF4500', '#2E8B57', '#DC143C', '#4682B4'
        ]
        color_index = index % len(colors)
        base_color = colors[color_index]
        # 10% opacity version of the color
        background_color = self._hex_to_rgba(base_color, 0.1)
        return base_color, background_color

    def _hex_to_rgba(self, hex_color, alpha):
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r, g, b, int(alpha * 255))