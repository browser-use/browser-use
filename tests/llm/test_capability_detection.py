"""Unit-tests for `browser_use.llm.config_test.test_llm_config`.

These tests rely only on langchain-core and do **not** hit any external API.
All mock LLMs subclass `BaseChatModel` and implement minimal behaviour to
simulate success / failure scenarios.
"""
from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from browser_use.llm.config_test import test_llm_config


class _BaseMockLLM(BaseChatModel):
    """Minimal mock LLM base-class (sync only)."""

    model: str = "mock-model"

    # ---- BaseChatModel abstract API ----------------------------------
    def _generate(self, messages, stop=None):  # type: ignore[override]
        raise NotImplementedError

    @property
    def _llm_type(self) -> str:
        return "mock_llm"

    # ---- helpers expected by test_llm_config -------------------------
    def with_structured_output(self, schema, include_raw=True, method=None):  # noqa: D401
        if getattr(self, "_fail_tool_call", False):
            raise RuntimeError("tool call not supported")
        return self  # return self so .invoke is available

    def invoke(self, prompt):  # type: ignore[override]
        # IQ check prompt detection
        if isinstance(prompt, str) and "capital" in prompt.lower():
            return "Paris"
        if isinstance(prompt, list):
            # simulate multi-message handling
            if getattr(self, "_fail_multi", False):
                raise RuntimeError("multiple human messages not supported")
            return "ack list"
        return "ok"


class MockToolsLLM(_BaseMockLLM):
    model: str = "gpt-4o-mini"


class MockFunctionLLM(_BaseMockLLM):
    model: str = "llama3-function"
    # Accept structured_output but expect function_calling


class MockNoToolsLLM(_BaseMockLLM):
    model: str = "old-model"
    _fail_tool_call: bool = True


class MockMultiFailLLM(_BaseMockLLM):
    model: str = "gemma-it"
    _fail_multi: bool = True


@pytest.mark.parametrize(
    "llm, requested, expected_method, tool_ok, multi_ok",
    [
        (MockToolsLLM(), "auto", "function_calling", True, True),  # heuristic default for non-Azure
        (MockFunctionLLM(), "function_calling", "function_calling", True, True),
        (MockNoToolsLLM(), "tools", "tools", False, True),
        (MockMultiFailLLM(), "auto", "function_calling", True, False),
    ],
)
def test_status_dict(llm, requested, expected_method, tool_ok, multi_ok):
    status = test_llm_config(llm, requested)
    assert status["selected_tool_calling_method"] == expected_method
    assert status["supports_tool_calling_method"] is tool_ok
    assert status["passed_iq_test"] is True  # all mocks answer Paris
    assert status["supports_multiple_human_msgs"] is multi_ok
