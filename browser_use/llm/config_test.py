"""
@file purpose: Detect and cache LLM capabilities (tool-calling, vision, latency, etc.)

Extended with IQ sanity-check and multi-human-message probe.
"""

from __future__ import annotations

import time
from typing import Any, Literal, TypedDict

try:
	from langchain_core.language_models.chat_models import BaseChatModel as LangChainBaseChatModel
	from langchain_core.messages import HumanMessage  # type: ignore
except ImportError:  # pragma: no cover
	# Fallback for pip install tests where langchain_core is not available
	LangChainBaseChatModel = object  # type: ignore
	
	class HumanMessage:  # type: ignore
		"""Fallback stub for HumanMessage when langchain_core is not available."""
		def __init__(self, content: str = '') -> None:
			self.content = content

__all__ = ['test_llm_config']


class LLMStatusDict(TypedDict, total=False):
	success: bool
	response_time: float | None  # seconds
	selected_tool_calling_method: str
	supports_tool_calling_method: bool
	vision_support: bool
	passed_iq_test: bool
	supports_multiple_human_msgs: bool


def _heuristic_select_method(llm) -> str:
	library = llm.__class__.__name__
	model_name = getattr(llm, 'model', '') or ''
	if library == 'AzureChatOpenAI' and 'gpt-4' in model_name.lower():
		return 'tools'
	return 'function_calling'


def _run_iq_check(llm) -> bool:
	"""Return True if model answers with *paris* for capital-of-France prompt."""
	try:
		raw = llm.invoke('What is the capital of France?')  # type: ignore[attr-defined]
		# Raw may be str or a Message object.
		if raw is None:
			return False
		if isinstance(raw, str):
			content = raw
		else:
			content = getattr(raw, 'content', str(raw))
		return 'paris' in content.lower()
	except Exception:
		return False


def _probe_multiple_msgs(llm) -> bool:
	"""Send two HumanMessages; if no exception ⇒ supported."""
	try:
		if HumanMessage == object:  # Fallback case
			return True  # Assume supported when langchain_core not available
		messages = [HumanMessage('hi'), HumanMessage('there')]
		llm.invoke(messages)  # type: ignore[arg-type, attr-defined]
		return True
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def test_llm_config(
	llm,  # Accept any type to handle fallback case
	tool_calling_method: str | Literal['auto', 'raw', 'json_mode', 'function_calling', 'tools'] = 'auto',
) -> LLMStatusDict:
	cached: dict[str, Any] | None = getattr(llm, '_llm_status_info', None)
	if cached:
		return cached  # type: ignore[return-value]

	status: LLMStatusDict = {
		'success': True,
		'response_time': None,
		'selected_tool_calling_method': '',
		'supports_tool_calling_method': True,
		'vision_support': bool(getattr(llm, 'supports_vision', False)),
		'passed_iq_test': False,
		'supports_multiple_human_msgs': True,
	}

	# choose method
	if tool_calling_method != 'auto':
		selected_method = tool_calling_method
	else:
		selected_method = _heuristic_select_method(llm)
	status['selected_tool_calling_method'] = selected_method

	t0 = time.perf_counter()

	# probe tool-calling (skip for raw/json)
	if selected_method not in {'json_mode', 'raw'}:
		try:
			llm.with_structured_output(dict, include_raw=True, method=selected_method)  # type: ignore[attr-defined]
		except Exception:
			status['supports_tool_calling_method'] = False
	# IQ test (best-effort)
	status['passed_iq_test'] = _run_iq_check(llm)
	# multi-msg support
	status['supports_multiple_human_msgs'] = _probe_multiple_msgs(llm)

	status['response_time'] = time.perf_counter() - t0

	setattr(llm, '_llm_status_info', status)
	return status
