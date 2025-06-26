from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from browser_use.browser import BrowserSession
from browser_use.browser.types import Page
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel

if TYPE_CHECKING:
	pass


class RegisteredAction(BaseModel):
	"""Model for a registered action"""

	name: str
	description: str
	function: Callable
	param_model: type[BaseModel]

	# filters: provide specific domains or a function to determine whether the action should be available on the given page or not
	domains: list[str] | None = None  # e.g. ['*.google.com', 'www.bing.com', 'yahoo.*]
	page_filter: Callable[[Page], bool] | None = None

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def prompt_description(self) -> str:
		"""Get a description of the action for the prompt"""
		skip_keys = ['title']
		s = f'{self.description}: \n'
		s += '{' + str(self.name) + ': '
		s += str(
			{
				k: {sub_k: sub_v for sub_k, sub_v in v.items() if sub_k not in skip_keys}
				for k, v in self.param_model.model_json_schema()['properties'].items()
			}
		)
		s += '}'
		return s


class ActionModel(BaseModel):
	"""Base model for dynamically created action models"""

	# this will have all the registered actions, e.g.
	# click_element = param_model = ClickElementParams
	# done = param_model = None
	#
	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	def get_index(self) -> int | None:
		"""Get the index of the action"""
		# {'clicked_element': {'index':5}}
		params = self.model_dump(exclude_unset=True).values()
		if not params:
			return None
		for param in params:
			if param is not None and 'index' in param:
				return param['index']
		return None

	def set_index(self, index: int):
		"""Overwrite the index of the action"""
		# Get the action name and params
		action_data = self.model_dump(exclude_unset=True)
		action_name = next(iter(action_data.keys()))
		action_params = getattr(self, action_name)

		# Update the index directly on the model
		if hasattr(action_params, 'index'):
			action_params.index = index


class ActionRegistry(BaseModel):
	"""Model representing the action registry"""

	actions: dict[str, RegisteredAction] = {}

	@staticmethod
	def _match_domains(domains: list[str] | None, url: str) -> bool:
		"""
		Match a list of domain glob patterns against a URL.

		Args:
			domains: A list of domain patterns that can include glob patterns (* wildcard)
			url: The URL to match against

		Returns:
			True if the URL's domain matches the pattern, False otherwise
		"""

		if domains is None or not url:
			return True

		# Use the centralized URL matching logic from utils
		from browser_use.utils import match_url_with_domain_pattern

		for domain_pattern in domains:
			if match_url_with_domain_pattern(url, domain_pattern):
				return True
		return False

	@staticmethod
	def _match_page_filter(page_filter: Callable[[Page], bool] | None, page: Page) -> bool:
		"""Match a page filter against a page"""
		if page_filter is None:
			return True
		return page_filter(page)

	def get_prompt_description(self, page: Page | None = None) -> str:
		"""Get a description of all actions for the prompt

		Args:
			page: If provided, filter actions by page using page_filter and domains.

		Returns:
			A string description of available actions.
			- If page is None: return only actions with no page_filter and no domains (for system prompt)
			- If page is provided: return only filtered actions that match the current page (excluding unfiltered actions)
		"""
		if page is None:
			# For system prompt (no page provided), include only actions with no filters
			return '\n'.join(
				action.prompt_description()
				for action in self.actions.values()
				if action.page_filter is None and action.domains is None
			)

		# only include filtered actions for the current page
		filtered_actions = []
		for action in self.actions.values():
			if not (action.domains or action.page_filter):
				# skip actions with no filters, they are already included in the system prompt
				continue

			domain_is_allowed = self._match_domains(action.domains, page.url)
			page_is_allowed = self._match_page_filter(action.page_filter, page)

			if domain_is_allowed and page_is_allowed:
				filtered_actions.append(action)

		return '\n'.join(action.prompt_description() for action in filtered_actions)


class SpecialActionParameters(BaseModel):
	"""Model defining all special parameters that can be injected into actions"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	# optional user-provided context object passed down from Agent(context=...)
	# e.g. can contain anything, external db connections, file handles, queues, runtime config objects, etc.
	# that you might want to be able to access quickly from within many of your actions
	# browser-use code doesn't use this at all, we just pass it down to your actions for convenience
	context: Any | None = None

	# browser-use session object, can be used to create new tabs, navigate, access playwright objects, etc.
	browser_session: BrowserSession | None = None

	# legacy support for actions that ask for the old model names
	browser: BrowserSession | None = None
	browser_context: BrowserSession | None = (
		None  # extra confusing, this is actually not referring to a playwright BrowserContext,
		# but rather the name for BrowserUse's own old BrowserContext object from <v0.2.0
		# should be deprecated then removed after v0.3.0 to avoid ambiguity
	)  # we can't change it too fast because many people's custom actions out in the wild expect this argument

	# actions can get the playwright Page, shortcut for page = await browser_session.get_current_page()
	page: Page | None = None

	# extra injected config if the action asks for these arg names
	page_extraction_llm: BaseChatModel | None = None
	file_system: FileSystem | None = None
	available_file_paths: list[str] | None = None
	has_sensitive_data: bool = False

	@classmethod
	def get_browser_requiring_params(cls) -> set[str]:
		"""Get parameter names that require browser_session"""
		return {'browser_session', 'browser', 'browser_context', 'page'}
