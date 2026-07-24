"""Tests for browser_use.agent.views"""

import json
import os
import tempfile

from browser_use.agent.views import AgentOutput, AgentHistoryList


def test_last_action_returns_none_on_empty_action_list():
    """last_action() must return None (not raise IndexError) when action list is empty."""
    history_data = {"history": [{"model_output": {"evaluation_previous_goal": "g", "memory": "m", "next_goal": "n", "action": []}, "result": [{"is_done": True}], "state": {"url": "http://test.com", "title": "t", "tabs": [], "interacted_element": [None]}}]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(history_data, f)
        tmpfile = f.name
    try:
        history = AgentHistoryList.load_from_file(tmpfile, AgentOutput)
        assert history.last_action() is None
    finally:
        os.unlink(tmpfile)
