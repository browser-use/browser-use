"""
SwiftAPI-Enabled Agent for Browser-Use

Wraps the browser-use Agent class with SwiftAPI attestation.
Every browser action requires cryptographic authorization before execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Generic, TypeVar

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList, AgentStructuredOutput
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools

from .attestation import AttestationProvider
from .config import SwiftAPIConfig
from .tools import SwiftAPITools

if TYPE_CHECKING:
	from browser_use.llm.base import BaseChatModel

logger = logging.getLogger(__name__)

Context = TypeVar('Context')


class SwiftAPIAgent(Agent, Generic[Context, AgentStructuredOutput]):
	"""Browser-use Agent with SwiftAPI attestation.

	Every action executed by this agent is verified against SwiftAPI policies.
	This provides cryptographic proof of authorization for enterprise use cases.

	Usage:
	    agent = SwiftAPIAgent(
	        task="Search for browser-use on GitHub",
	        llm=ChatOpenAI(model="gpt-4"),
	        swiftapi_key="swiftapi_live_..."
	    )
	    result = await agent.run()

	All actions will be attested via SwiftAPI before execution.
	If attestation fails, the action is blocked and the agent receives feedback.
	"""

	def __init__(
		self,
		task: str,
		llm: BaseChatModel | None = None,
		# SwiftAPI Configuration
		swiftapi_key: str | None = None,
		swiftapi_config: SwiftAPIConfig | None = None,
		attestation_provider: AttestationProvider | None = None,
		attest_all_actions: bool = False,
		# Browser configuration
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		browser: BrowserSession | None = None,
		# Tools (will be wrapped with SwiftAPI if not SwiftAPITools)
		tools: Tools[Context] | None = None,
		controller: Tools[Context] | None = None,
		# All other Agent parameters
		**kwargs,
	):
		"""Initialize SwiftAPI-enabled Agent.

		Args:
		    task: The task for the agent to complete.
		    llm: Language model to use.
		    swiftapi_key: SwiftAPI authority key.
		    swiftapi_config: Full SwiftAPIConfig object.
		    attestation_provider: Custom attestation provider.
		    attest_all_actions: If True, attest read-only actions too.
		    browser_profile: Browser profile configuration.
		    browser_session: Existing browser session to use.
		    browser: Alias for browser_session.
		    tools: Tools instance (will be wrapped with SwiftAPI).
		    controller: Alias for tools.
		    **kwargs: All other Agent parameters.
		"""
		# Set up SwiftAPI config
		if swiftapi_config is not None:
			self._swiftapi_config = swiftapi_config
		else:
			self._swiftapi_config = SwiftAPIConfig(api_key=swiftapi_key)

		# Wrap or create SwiftAPI-enabled tools
		provided_tools = tools or controller
		if provided_tools is not None:
			if isinstance(provided_tools, SwiftAPITools):
				# Already SwiftAPI-enabled
				swiftapi_tools = provided_tools
			else:
				# Wrap existing tools - we need to create new SwiftAPITools
				# and copy the registry from the provided tools
				logger.info('[SwiftAPI] Wrapping provided Tools with SwiftAPI attestation')
				swiftapi_tools = SwiftAPITools(
					config=self._swiftapi_config,
					attestation_provider=attestation_provider,
					attest_all_actions=attest_all_actions,
				)
				# Share registry reference (intentional - tools should see same actions)
				swiftapi_tools.registry = provided_tools.registry
		else:
			# Create new SwiftAPI-enabled tools
			swiftapi_tools = SwiftAPITools(
				config=self._swiftapi_config,
				attestation_provider=attestation_provider,
				attest_all_actions=attest_all_actions,
			)

		# Log SwiftAPI status
		if self._swiftapi_config.is_configured:
			logger.info(
				f'\033[32m[SwiftAPI]\033[0m Agent initialized with attestation (authority: {self._swiftapi_config.base_url})'
			)
		else:
			logger.warning(
				'\033[33m[SwiftAPI]\033[0m Agent initialized WITHOUT attestation. '
				'All high-risk actions will be blocked. Set SWIFTAPI_KEY to enable.'
			)

		# Initialize parent Agent with SwiftAPI-enabled tools
		super().__init__(  # type: ignore[reportAttributeAccessIssue]
			task=task,
			llm=llm,
			browser_profile=browser_profile,
			browser_session=browser_session,
			browser=browser,
			tools=swiftapi_tools,
			**kwargs,
		)

		self._swiftapi_tools = swiftapi_tools

	@property
	def swiftapi_config(self) -> SwiftAPIConfig:
		"""Get the SwiftAPI configuration."""
		return self._swiftapi_config

	async def run(
		self,
		max_steps: int = 100,
		on_step_start=None,
		on_step_end=None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Run the agent with SwiftAPI attestation.

		All actions will be verified against SwiftAPI policies before execution.
		"""
		try:
			return await super().run(  # type: ignore[reportAttributeAccessIssue]
				max_steps=max_steps,
				on_step_start=on_step_start,
				on_step_end=on_step_end,
			)
		finally:
			# Clean up SwiftAPI resources
			if hasattr(self._swiftapi_tools, 'close'):
				await self._swiftapi_tools.close()
