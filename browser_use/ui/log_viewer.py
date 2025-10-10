"""Minimal Textual-based log viewer (PoC).

This is a lightweight proof-of-concept. It expects `textual` to be installed.
Run the demo script `examples/logviewer_demo.py` to try it out.
"""
from __future__ import annotations

import asyncio
from typing import Any

try:
    from textual.app import App
    from textual.widgets import Header, Footer, DataTable, Input
    from textual import events
except Exception as e:  # pragma: no cover - runtime import
    raise ImportError(
        "textual is required for the TUI viewer. Install with `pip install textual>=0.22.0`"
    ) from e


class LogViewerApp(App):
    """A very small Textual app that displays logs in a two-column table.

    PoC: left column is level, right column is message. A background task pulls
    rows from an asyncio.Queue and appends them to the table.
    """

    CSS = """
    # minimal styling placeholder
    """

    def __init__(
        self,
        queue: "asyncio.Queue[dict[str, Any]]",
        max_rows: int = 50000,
        batch_interval: float = 0.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.queue = queue
        self._next_id = 1
        # performance tuning
        self.max_rows = max_rows
        self.batch_interval = batch_interval
        # in-memory buffer of rows (for fast filtering/search)
        self._rows: list[dict] = []
        self._level_filter: set[str] | None = None
        self._follow_tail = True
        # search state
        self._last_search = ""
        self._search_matches: list[int] = []
        self._current_search_idx: int | None = None
        # available levels for quick cycling
        self._levels = [None, {"DEBUG"}, {"INFO"}, {"WARNING"}, {"ERROR"}, {"CRITICAL"}]
        self._level_index = 0


    async def on_mount(self, event: events.Mount) -> None:  # type: ignore[override]
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("Level", "Message")

        # mount header/footer and table using dock for layout
        await self.view.dock(Header(), edge="top")
        await self.view.dock(Footer(), edge="bottom")
        await self.view.dock(self.table, edge="left")

        # start background poller
        self.set_interval(self.batch_interval, self._poll_queue)

        # key handlers
        self.bind("q", "quit", "Quit")
        self.bind("G", "go_bottom", "Go bottom")
        self.bind("g", "maybe_gg", "gg (press twice)")
        self.bind("/", "search", "Search")
        self.bind(":", "command_mode", "Command")
        self.bind("n", "next_search", "Next search")
        self.bind("N", "prev_search", "Prev search")
        self.bind("f", "toggle_follow", "Toggle follow")
        self.bind("l", "cycle_level", "Cycle level filter")

        # Input widgets (hidden until invoked)
        self.search_input = Input(placeholder="/search", visible=False)
        self.command_input = Input(placeholder=":command", visible=False)
        await self.view.dock(self.search_input, edge="bottom", size=3)
        await self.view.dock(self.command_input, edge="bottom", size=3)

    # event handlers
    # Prefer Textual message handlers instead of assigning callback attributes.
    # We'll handle Input.Submitted messages via `on_input_submitted` below.

        # state for double-g detection (gg)
        self._last_g_time = 0.0

    async def _poll_queue(self) -> None:
        """Drain new rows from the queue, coalesce updates, and update the table in batches."""
        drained = False
        try:
            while True:
                row = self.queue.get_nowait()
                drained = True
                self._rows.append(row)

                # enforce max buffer size
                if len(self._rows) > self.max_rows:
                    # discard oldest rows
                    excess = len(self._rows) - self.max_rows
                    self._rows = self._rows[excess:]

        except asyncio.QueueEmpty:
            pass

        if not drained:
            return

        # apply filter and update table once per batch
        # For performance, re-create the visible rows each batch but cap message length
        self.table.clear()
        max_msg_len = 1000
        for row in self._rows:
            level = str(row.get("level", ""))
            if self._level_filter and level not in self._level_filter:
                continue
            msg_raw = str(row.get("message", ""))
            msg = msg_raw if len(msg_raw) <= max_msg_len else (msg_raw[: max_msg_len - 3] + "...")
            self.table.add_row(level, msg)

        # follow tail if requested
        if self._follow_tail:
            try:
                # move selection to last row
                self.table.cursor_coordinate = (len(self.table.rows) - 1, 0)
            except Exception:
                pass

    async def action_quit(self) -> None:  # pragma: no cover - UI
        await self.shutdown()

    async def action_go_bottom(self) -> None:
        """Go to the bottom (latest log)."""
        try:
            self.table.cursor_coordinate = (len(self.table.rows) - 1, 0)
        except Exception:
            pass

    async def action_maybe_gg(self) -> None:
        """Detect double 'g' for gg -> go to top."""
        import time

        now = time.time()
        if now - self._last_g_time < 0.4:
            # interpret as gg
            try:
                self.table.cursor_coordinate = (0, 0)
            except Exception:
                pass
        self._last_g_time = now

    async def action_search(self) -> None:
        """Show the search input widget and focus it (non-blocking)."""
        self.search_input.visible = True
        await self.search_input.focus()

    async def action_command_mode(self) -> None:
        """Show the command input widget and focus it (non-blocking)."""
        self.command_input.visible = True
        await self.command_input.focus()

    async def _on_search_submitted(self, value: str) -> None:
        """Handler called when the search input is submitted."""
        self.search_input.visible = False
        term = value.strip()
        if not term:
            return
        self._last_search = term
        self._search_matches = [i for i, r in enumerate(self._rows) if term.lower() in str(r.get("message", "")).lower()]
        if self._search_matches:
            self._current_search_idx = 0
            idx = self._search_matches[0]
            try:
                self.table.cursor_coordinate = (idx, 0)
            except Exception:
                pass

    async def _on_command_submitted(self, value: str) -> None:
        """Handler for command input (non-blocking)."""
        self.command_input.visible = False
        cmd = value.strip()
        if not cmd:
            return
        parts = cmd.split()
        if parts[0] == "q":
            await self.action_quit()
        elif parts[0] == "filter" and len(parts) > 1:
            levels = {p.strip().upper() for p in parts[1].split(",")}
            self._level_filter = levels
            await self._poll_queue()
        elif parts[0] == "clearfilter":
            self._level_filter = None
            await self._poll_queue()

    async def action_next_search(self) -> None:
        """Go to next search match (n)."""
        if not self._search_matches:
            return
        if self._current_search_idx is None:
            self._current_search_idx = 0
        else:
            self._current_search_idx = (self._current_search_idx + 1) % len(self._search_matches)
        idx = self._search_matches[self._current_search_idx]
        try:
            self.table.cursor_coordinate = (idx, 0)
        except Exception:
            pass

    async def action_prev_search(self) -> None:
        """Go to previous search match (N)."""
        if not self._search_matches:
            return
        if self._current_search_idx is None:
            self._current_search_idx = 0
        else:
            self._current_search_idx = (self._current_search_idx - 1) % len(self._search_matches)
        idx = self._search_matches[self._current_search_idx]
        try:
            self.table.cursor_coordinate = (idx, 0)
        except Exception:
            pass

    async def action_toggle_follow(self) -> None:
        """Toggle follow-tail behavior (f)."""
        self._follow_tail = not self._follow_tail

    async def action_cycle_level(self) -> None:
        """Cycle quick level filters (l)."""
        self._level_index = (self._level_index + 1) % len(self._levels)
        self._level_filter = self._levels[self._level_index]
        await self._poll_queue()

    async def on_input_submitted(self, message: Input.Submitted) -> None:  # type: ignore[type-arg]
        """Handle Input.Submitted messages from Textual Input widgets.

        This replaces direct assignment of `on_submit` callbacks and dispatches
        to the existing async handlers depending on which Input sent the
        message.
        """
        # message.input is the Input widget that was submitted
        sender = message.input
        # value is the submitted text
        value = message.value

        # route to the appropriate handler
        if sender is self.search_input:
            await self._on_search_submitted(value)
        elif sender is self.command_input:
            await self._on_command_submitted(value)
        else:
            # unknown input - ignore
            return



def run_log_viewer(queue: "asyncio.Queue[dict[str, Any]]") -> None:
    """Run the textual log viewer. This is blocking - run it in a dedicated terminal.

    For embedding into an async program, prefer `await LogViewerApp(...).run_async()` if available in
    your textual version.
    """
    app = LogViewerApp(queue=queue)
    app.run()
