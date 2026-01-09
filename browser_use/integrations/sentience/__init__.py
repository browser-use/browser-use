"""Sentience integration for browser-use Agent."""

from .state_injector import build_sentience_state, format_snapshot_for_llm

__all__ = ["build_sentience_state", "format_snapshot_for_llm"]
