# logview.py
import asyncio
import random
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Input
from textual import events

class LogViewerApp(App):
    CSS = """
    DataTable {
        height: 90%;
        width: 100%;
        border: round yellow;
    }
    Input {
        width: 100%;
        height: 3;
    }
    """

    def compose(self) -> ComposeResult:
        # DataTable for logs
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("Level", "Message")
        yield self.table

        # Input for search
        self.search_input = Input(placeholder="Type / to search...", visible=False)
        yield self.search_input

    async def add_log(self, level: str, message: str):
        """Add a log row and scroll to bottom."""
        color = {
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "DEBUG": "cyan"
        }.get(level, "white")

        # Add the row
        self.table.add_row(f"[{color}]{level}[/{color}]", message)

        # Move cursor to last row
        self.table.cursor_row = len(self.table.rows) - 1
        self.table.scroll_cursor_into_view()

    async def generate_test_logs(self):
        """Generate random logs every 1 second."""
        levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        messages = [
            'System initialized',
            'Connection established',
            'Warning: high memory usage',
            'Error: failed to load module',
            'User logged in'
        ]
        while True:
            level = random.choice(levels)
            message = random.choice(messages)
            await self.add_log(level, message)
            await asyncio.sleep(1)

    async def on_key(self, event: events.Key):
        key = event.key

        # Vim-like scrolling
        if key == "j":
            self.table.move_cursor_down()
        elif key == "k":
            self.table.move_cursor_up()
        elif key == "g":
            self.table.cursor_row = 0
            self.table.scroll_cursor_into_view()
        elif key == "G":
            self.table.cursor_row = len(self.table.rows) - 1
            self.table.scroll_cursor_into_view()
        elif key == "/":
            self.search_input.visible = True
            self.search_input.focus()

    async def on_mount(self):
        """Start generating logs after app mounts."""
        self.set_interval(0, self.generate_test_logs)  # Non-blocking

if __name__ == "__main__":
    app = LogViewerApp()
    app.run()
