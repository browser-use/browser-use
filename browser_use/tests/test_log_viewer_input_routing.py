import asyncio

from textual.widgets import Input

from browser_use.ui.log_viewer import LogViewerApp


def make_msg(input_widget: Input, value: str):
    """Return a simple object resembling Textual's Input.Submitted message.

    We avoid constructing the real message class to keep the test lightweight.
    """

    class Msg:
        def __init__(self, input_widget, value):
            self.input = input_widget
            self.value = value

    return Msg(input_widget, value)


def test_search_input_routing():
    q: asyncio.Queue[dict] = asyncio.Queue()
    app = LogViewerApp(queue=q)

    # attach Input widgets the same way the app does in on_mount
    app.search_input = Input(placeholder="/search")
    app.command_input = Input(placeholder=":command")

    # prepare rows so a search has something to match
    app._rows = [
        {"message": "hello world" , "level": "INFO"},
        {"message": "find-me Foo bar" , "level": "DEBUG"},
        {"message": "another line" , "level": "ERROR"},
    ]

    # simulate submitting the search input
    msg = make_msg(app.search_input, "find-me")
    asyncio.run(app.on_input_submitted(msg))

    assert app._last_search == "find-me"
    assert len(app._search_matches) >= 1
    # verify the first matched row indeed contains the search term
    first_idx = app._search_matches[0]
    assert "find-me" in app._rows[first_idx]["message"].lower()


def test_command_input_filter_routing():
    q: asyncio.Queue[dict] = asyncio.Queue()
    app = LogViewerApp(queue=q)

    app.search_input = Input(placeholder="/search")
    app.command_input = Input(placeholder=":command")

    # submit a filter command
    msg = make_msg(app.command_input, "filter INFO,ERROR")
    asyncio.run(app.on_input_submitted(msg))

    assert app._level_filter == {"INFO", "ERROR"}
