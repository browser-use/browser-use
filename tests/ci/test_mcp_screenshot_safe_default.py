"""Tests for MCP screenshot context-poisoning fix (Issue #4742).

Bug: screenshot blobs embedded in MCP tool results were stored in the
conversation history of clients like Claude Code.  On every subsequent
turn the Anthropic API received the full history (including the blob)
and rejected it with HTTP 400 "Could not process image", permanently
bricking the session.

Fix: BrowserUseServer._save_screenshot_to_temp() writes raw PNG bytes
to a temp file and the tool result carries only the file path as plain
text.  This is the default behaviour for both browser_screenshot and
browser_get_state.

All tests below are pure-unit (no browser, no network) and rely only on
stdlib mocks.
"""

import base64
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TINY_PNG = (
    b'\x89PNG\r\n\x1a\n'  # PNG signature
    b'\x00\x00\x00\rIHDR'  # IHDR chunk length + type
    b'\x00\x00\x00\x01'    # width = 1
    b'\x00\x00\x00\x01'    # height = 1
    b'\x08\x02'            # bit depth = 8, colour type = RGB
    b'\x00\x00\x00'        # compression, filter, interlace
    b'\x90wS\xde'          # CRC
    b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)

_TINY_PNG_B64 = base64.b64encode(_TINY_PNG).decode()


def _make_server():
    """Return a BrowserUseServer instance with minimal mocking."""
    # Importing inside the function avoids triggering the MCP SDK at module load
    # time (it writes to stdout which breaks pytest output capture).
    with patch('browser_use.mcp.server.MCP_AVAILABLE', True), \
         patch('browser_use.mcp.server.Server'):
        from browser_use.mcp.server import BrowserUseServer
        server = BrowserUseServer.__new__(BrowserUseServer)
        server.active_sessions = {}
        server.session_timeout_minutes = 10
        server._cleanup_task = None
        server.browser_session = None
        server.tools = None
        server.llm = None
        server.file_system = None
        return server


# ---------------------------------------------------------------------------
# _save_screenshot_to_temp
# ---------------------------------------------------------------------------


class TestSaveScreenshotToTemp:
    """Tests for the _save_screenshot_to_temp() helper."""

    def test_writes_raw_bytes_to_temp_file(self):
        server = _make_server()
        path = server._save_screenshot_to_temp(_TINY_PNG)
        try:
            assert os.path.exists(path)
            with open(path, 'rb') as fh:
                assert fh.read() == _TINY_PNG
        finally:
            os.unlink(path)

    def test_returned_path_has_png_suffix(self):
        server = _make_server()
        path = server._save_screenshot_to_temp(_TINY_PNG)
        try:
            assert path.endswith('.png')
        finally:
            os.unlink(path)

    def test_returned_path_has_descriptive_prefix(self):
        server = _make_server()
        path = server._save_screenshot_to_temp(_TINY_PNG)
        try:
            assert os.path.basename(path).startswith('browser_use_screenshot_')
        finally:
            os.unlink(path)

    def test_cleans_up_temp_file_on_write_error(self):
        """If writing fails the temp file must not be left behind."""
        server = _make_server()

        original_mkstemp = tempfile.mkstemp

        def fake_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            return fd, path

        created_path = None

        def capturing_mkstemp(*args, **kwargs):
            nonlocal created_path
            fd, path = original_mkstemp(*args, **kwargs)
            created_path = path
            return fd, path

        with patch('tempfile.mkstemp', side_effect=capturing_mkstemp), \
             patch('os.fdopen', side_effect=OSError('disk full')):
            with pytest.raises(OSError, match='disk full'):
                server._save_screenshot_to_temp(_TINY_PNG)

        # The partial temp file must have been removed
        assert created_path is not None
        assert not os.path.exists(created_path), (
            f'Temp file {created_path} was not cleaned up after write failure'
        )

    def test_accepts_bytes_not_str(self):
        """Callers must not need to base64-encode before calling the helper."""
        server = _make_server()
        # Passing str should raise TypeError, not silently corrupt the file
        with pytest.raises((TypeError, AttributeError)):
            server._save_screenshot_to_temp(_TINY_PNG_B64)  # str, not bytes


# ---------------------------------------------------------------------------
# _screenshot() — safe default
# ---------------------------------------------------------------------------


class TestScreenshotSafeDefault:
    """Tests for BrowserUseServer._screenshot()."""

    def _make_server_with_session(self):
        server = _make_server()
        mock_session = MagicMock()
        mock_session.id = 'test-session-id'
        mock_session.take_screenshot = AsyncMock(return_value=_TINY_PNG)
        mock_session.get_browser_state_summary = AsyncMock(return_value=MagicMock(page_info=None))
        server.browser_session = mock_session
        server.active_sessions = {'test-session-id': {'last_activity': 0}}
        return server

    @pytest.mark.asyncio
    async def test_default_saves_to_file_not_inline(self):
        """save_to_file=True (default) must return filepath, not b64 data."""
        server = self._make_server_with_session()
        _meta, screenshot_b64, filepath = await server._screenshot()

        assert filepath is not None, 'Expected a file path, got None'
        assert screenshot_b64 is None, 'Expected no inline b64 data with save_to_file=True'
        assert os.path.exists(filepath)
        os.unlink(filepath)

    @pytest.mark.asyncio
    async def test_default_file_contains_correct_png_bytes(self):
        server = self._make_server_with_session()
        _meta, _b64, filepath = await server._screenshot()

        with open(filepath, 'rb') as fh:
            assert fh.read() == _TINY_PNG
        os.unlink(filepath)

    @pytest.mark.asyncio
    async def test_inline_mode_returns_b64_not_filepath(self):
        """save_to_file=False must return inline b64 and no filepath."""
        server = self._make_server_with_session()
        _meta, screenshot_b64, filepath = await server._screenshot(save_to_file=False)

        assert screenshot_b64 is not None, 'Expected inline b64 data'
        assert filepath is None, 'Expected no filepath in inline mode'
        assert base64.b64decode(screenshot_b64) == _TINY_PNG

    @pytest.mark.asyncio
    async def test_no_redundant_encode_decode_in_save_path(self):
        """_screenshot must NOT encode raw bytes to b64 only to decode back.

        Regression guard: previously the code called
            self._save_screenshot_to_temp(base64.b64encode(raw_bytes).decode())
        and the helper immediately decoded it back.  Now raw bytes flow
        straight through.
        """
        server = self._make_server_with_session()
        encode_calls = []

        original_b64encode = base64.b64encode

        def spy_b64encode(data):
            encode_calls.append(data)
            return original_b64encode(data)

        with patch('base64.b64encode', side_effect=spy_b64encode):
            _meta, _b64, filepath = await server._screenshot(save_to_file=True)

        try:
            # When saving to file, b64encode must NOT be called at all
            # (the raw bytes go straight to disk).
            assert encode_calls == [], (
                'base64.b64encode should not be called when save_to_file=True; '
                f'was called {len(encode_calls)} time(s)'
            )
        finally:
            if filepath:
                os.unlink(filepath)

    @pytest.mark.asyncio
    async def test_size_bytes_matches_file_on_disk(self):
        server = self._make_server_with_session()
        meta_json, _b64, filepath = await server._screenshot(save_to_file=True)

        import json
        meta = json.loads(meta_json)
        expected = os.path.getsize(filepath)
        assert meta['size_bytes'] == expected, (
            f"size_bytes {meta['size_bytes']} != actual file size {expected}"
        )
        os.unlink(filepath)

    @pytest.mark.asyncio
    async def test_size_bytes_matches_raw_length_in_inline_mode(self):
        server = self._make_server_with_session()
        meta_json, _b64, _fp = await server._screenshot(save_to_file=False)

        import json
        meta = json.loads(meta_json)
        assert meta['size_bytes'] == len(_TINY_PNG)

    @pytest.mark.asyncio
    async def test_returns_error_when_no_browser_session(self):
        server = _make_server()  # no browser_session set
        meta, b64, fp = await server._screenshot()
        assert 'Error' in meta
        assert b64 is None
        assert fp is None


# ---------------------------------------------------------------------------
# _get_browser_state() — screenshot path
# ---------------------------------------------------------------------------


class TestGetBrowserStateScreenshot:
    """Tests for the screenshot branches inside _get_browser_state()."""

    def _make_server_with_state(self, has_screenshot: bool = True):
        server = _make_server()
        mock_state = MagicMock()
        mock_state.url = 'https://example.com'
        mock_state.title = 'Example'
        mock_state.tabs = []
        mock_state.page_info = None
        mock_state.dom_state = MagicMock()
        mock_state.dom_state.selector_map = {}
        mock_state.screenshot = _TINY_PNG_B64 if has_screenshot else None

        mock_session = MagicMock()
        mock_session.get_browser_state_summary = AsyncMock(return_value=mock_state)
        server.browser_session = mock_session
        return server

    @pytest.mark.asyncio
    async def test_no_screenshot_when_include_false(self):
        server = self._make_server_with_state()
        _json, b64, fp = await server._get_browser_state(include_screenshot=False)
        assert b64 is None
        assert fp is None

    @pytest.mark.asyncio
    async def test_save_to_file_true_returns_filepath(self):
        server = self._make_server_with_state()
        _json, b64, fp = await server._get_browser_state(
            include_screenshot=True, save_to_file=True
        )
        assert fp is not None
        assert b64 is None
        assert os.path.exists(fp)
        with open(fp, 'rb') as fh:
            assert fh.read() == _TINY_PNG   # decoded from b64, written as raw bytes
        os.unlink(fp)

    @pytest.mark.asyncio
    async def test_save_to_file_false_returns_inline_b64(self):
        server = self._make_server_with_state()
        _json, b64, fp = await server._get_browser_state(
            include_screenshot=True, save_to_file=False
        )
        assert b64 == _TINY_PNG_B64
        assert fp is None

    @pytest.mark.asyncio
    async def test_no_double_decode_in_save_path(self):
        """_get_browser_state must decode state.screenshot ONCE, not twice.

        Regression guard for the earlier bug where the helper accepted a b64
        string and decoded it internally — callers that already had raw bytes
        would have double-decoded.
        """
        server = self._make_server_with_state()
        decode_calls = []

        original_b64decode = base64.b64decode

        def spy_b64decode(data, **kwargs):
            decode_calls.append(data)
            return original_b64decode(data, **kwargs)

        with patch('base64.b64decode', side_effect=spy_b64decode):
            _json, _b64, fp = await server._get_browser_state(
                include_screenshot=True, save_to_file=True
            )

        try:
            assert len(decode_calls) == 1, (
                f'base64.b64decode should be called exactly once; called {len(decode_calls)} time(s)'
            )
        finally:
            if fp:
                os.unlink(fp)

    @pytest.mark.asyncio
    async def test_returns_error_when_no_browser_session(self):
        server = _make_server()
        state_json, b64, fp = await server._get_browser_state(include_screenshot=True)
        assert 'Error' in state_json
        assert b64 is None
        assert fp is None
