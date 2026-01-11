import logging

import pytest

from browser_use.cli_helpers import (
        RichLogHandler,
        get_llm,
        is_scroll_at_bottom,
        pause_agent_run,
        resume_agent_run,
)
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.deepseek.chat import ChatDeepSeek


class DummyScrollOffset:
        def __init__(self, y: int):
                self.y = y


class DummyLog:
        def __init__(self, scroll_y: int, max_scroll_y: int):
                self.scroll_y = scroll_y
                self.max_scroll_y = max_scroll_y
                self.messages: list[str] = []
                self.scrolled = False

        def write(self, message: str) -> None:
                self.messages.append(message)

        def scroll_end(self, animate: bool = False) -> None:
                self.scrolled = True
                self.scroll_y = self.max_scroll_y


class DummyAgentState:
        def __init__(self):
                self.paused = False


class DummyAgent:
        def __init__(self):
                self.running = True
                self.state = DummyAgentState()

        def pause(self) -> None:
                self.state.paused = True

        def resume(self) -> None:
                self.state.paused = False


def test_richlog_handler_respects_user_scroll():
        log = DummyLog(scroll_y=0, max_scroll_y=5)
        handler = RichLogHandler(log)
        record = logging.LogRecord('test', logging.INFO, __file__, 0, 'message', (), None)

        handler.emit(record)
        assert log.messages[-1] == 'message'
        assert not log.scrolled

        # Simulate user at bottom
        log.scroll_y = log.max_scroll_y
        handler.emit(record)
        assert log.scrolled


def test_is_scroll_at_bottom_uses_offsets():
        class OffsetLog:
                def __init__(self):
                        self.max_scroll_y = 2
                        self.scroll_offset = DummyScrollOffset(y=1)

        assert not is_scroll_at_bottom(OffsetLog())
        bottom_log = OffsetLog()
        bottom_log.scroll_offset.y = 3
        assert is_scroll_at_bottom(bottom_log)


def test_pause_and_resume_helpers_toggle_state():
        agent = DummyAgent()
        output = DummyLog(scroll_y=0, max_scroll_y=0)

        paused = pause_agent_run(agent, output)
        assert paused
        assert agent.state.paused

        resumed = resume_agent_run(agent, output)
        assert resumed
        assert not agent.state.paused


def test_get_llm_prefers_browser_use(monkeypatch):
        monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-key')
        config = {'model': {'api_keys': {}}}

        llm = get_llm(config)

        assert isinstance(llm, ChatBrowserUse)
        assert llm.model.startswith('bu-')


def test_get_llm_honors_specific_model(monkeypatch):
        monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-key')
        config = {'model': {'name': 'deepseek-chat', 'api_keys': {}}}

        llm = get_llm(config)

        assert isinstance(llm, ChatDeepSeek)
        assert llm.model == 'deepseek-chat'
