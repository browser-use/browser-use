"""Agent variable detection and rerun substitution helpers."""

import logging

from browser_use.agent.variable_detector import detect_variables_in_history, substitute_variables_in_history
from browser_use.agent.views import AgentHistoryList, DetectedVariable


class AgentVariableMixin:
	history: AgentHistoryList
	logger: logging.Logger

	def detect_variables(self) -> dict[str, DetectedVariable]:
		"""Detect reusable variables in agent history."""
		return detect_variables_in_history(self.history)

	def _substitute_variables_in_history(self, history: AgentHistoryList, variables: dict[str, str]) -> AgentHistoryList:
		"""Substitute variables in history with new values for rerunning with different data."""
		return substitute_variables_in_history(history, variables, substitution_logger=self.logger)
