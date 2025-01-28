from playwright.async_api import Page

class HighlightManager:
    def __init__(self, page: Page):
        self.page = page

    async def highlight_element(self, position, index):
        await self._create_highlight_container()
        await self._create_highlight_overlay(position, index)
        await self._create_label(position, index)

    async def _create_highlight_container(self):
        container_script = """
        if (!document.getElementById('playwright-highlight-container')) {
            const container = document.createElement('div');
            container.id = 'playwright-highlight-container';
            container.style.position = 'absolute';
            container.style.pointerEvents = 'none';
            container.style.top = '0';
            container.style.left = '0';
            container.style.width = '100%';
            container.style.height = '100%';
            container.style.zIndex = '2147483647'; // Maximum z-index value
            document.body.appendChild(container);
        }
        """
        await self.page.evaluate(container_script)

    async def _create_highlight_overlay(self, position, index):
        base_color, background_color = self._generate_color(index)
        overlay_script = f"""
        (position) => {{
            const overlay = document.createElement('div');
            overlay.style.position = 'absolute';
            overlay.style.border = '2px solid {base_color}';
            overlay.style.backgroundColor = '{background_color}';
            overlay.style.pointerEvents = 'none';
            overlay.style.boxSizing = 'border-box';
            overlay.style.top = `${{position.top}}px`;
            overlay.style.left = `${{position.left}}px`;
            overlay.style.width = `${{position.width}}px`;
            overlay.style.height = `${{position.height}}px`;
            overlay.setAttribute('browser-user-highlight-id', `playwright-highlight-${index}`);

            document.getElementById('playwright-highlight-container').appendChild(overlay);
        }}
        """
        await self.page.evaluate(overlay_script, position)

    async def _create_label(self, position, index):
        base_color, _ = self._generate_color(index)
        label_script = f"""
        (position) => {{
            const label = document.createElement('div');
            label.className = 'playwright-highlight-label';
            label.style.position = 'absolute';
            label.style.background = '{base_color}';
            label.style.color = 'white';
            label.style.padding = '1px 4px';
            label.style.borderRadius = '4px';
            label.style.fontSize = `${{Math.min(12, Math.max(8, position.height / 2))}}px`; // Responsive font size
            label.textContent = {index};

            const labelWidth = 20; // Approximate width
            const labelHeight = 16; // Approximate height

            let labelTop = position.top + 2;
            let labelLeft = position.left + position.width - labelWidth - 2;

            if (position.width < labelWidth + 4 || position.height < labelHeight + 4) {{
                labelTop = position.top - labelHeight - 2;
                labelLeft = position.left + position.width - labelWidth;
            }}

            label.style.top = `${{labelTop}}px`;
            label.style.left = `${{labelLeft}}px`;

            document.getElementById('playwright-highlight-container').appendChild(label);
        }}
        """
        await self.page.evaluate(label_script, position)

    def _generate_color(self, index):
        colors = [
            '#FF0000', '#00FF00', '#0000FF', '#FFA500',
            '#800080', '#008080', '#FF69B4', '#4B0082',
            '#FF4500', '#2E8B57', '#DC143C', '#4682B4'
        ]
        color_index = index % len(colors)
        base_color = colors[color_index]
        background_color = f"{base_color}1A"  # 10% opacity version of the color
        return base_color, background_color