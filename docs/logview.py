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
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("Level", "Message")
        yield self.table

        self.search_input = Input(placeholder="Type / to search...")
        self.search_input.display = False  # Hide the input initially
        yield self.search_input
    async def add_log(self, level: str, message: str):
        color = {
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "DEBUG": "cyan"
        }.get(level, "white")

        self.table.add_row(f"[{color}]{level}[/{color}]", message)
        self.table.cursor_row = len(self.table.rows) - 1
        self.table.scroll_cursor_into_view()

    async def generate_test_logs(self):
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
            self.search_input.display = True
            self.search_input.focus()

    async def on_mount(self):
        asyncio.create_task(self.generate_test_logs())


if __name__ == "__main__":
    app = LogViewerApp()
    app.run()
