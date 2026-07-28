import asyncio
import gc
import inspect
import json
import logging
import re
from typing import Any

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import AgentInput, AgentOutput, AgentStepInfo
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage
from browser_use.logging_config import setup_logging
from browser_use.observability import observe_debug, record_dlp_metrics
from browser_use.sanitization.policy import load_dlp_config_from_env
from browser_use.sanitization.redactors import sanitize_messages

logger = logging.getLogger(__name__)

# ... existing imports and code above are preserved in upstream; this file is trimmed for API patch ...

async def _invoke_llm_with_sanitization(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    **kwargs: Any,
):
    """Sanitize messages before LLM invocation, record metrics, then call ainvoke."""
    cfg = load_dlp_config_from_env()
    if cfg.enabled and cfg.mode != "off":
        sanitized, findings = sanitize_messages(messages, cfg)
        if findings:
            record_dlp_metrics(findings)
        messages = sanitized
    return await llm.ainvoke(messages, **kwargs)


@observe_debug(ignore_input=True, ignore_output=True, name='agent_run_step')
async def run_step(
    llm: BaseChatModel,
    manager: MessageManager,
    step_info: AgentStepInfo,
    **kwargs: Any,
) -> AgentOutput:
    """Single agent step that prepares messages and calls the LLM.

    This wrapper injects DLP sanitization pre-LLM.
    """
    # Prepare messages from the manager
    messages = manager.get_messages()

    # Sanitize + invoke
    completion = await _invoke_llm_with_sanitization(llm, messages, **kwargs)

    # Upstream code converts completion to AgentOutput; we keep the interface
    # Placeholder: adapt to real conversion present upstream
    output = AgentOutput(current_state=completion, tool_calls=[], messages=messages)
    return output
