from collections.abc import Callable

from patchright.async_api import Page
from pydantic import BaseModel, ConfigDict


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
	model_config = ConfigDict(arbitrary_types_allowed=True)

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
			domain_patterns: A list of domain patterns that can include glob patterns (* wildcard)
			url: The URL to match against

		Returns:
			True if the URL's domain matches the pattern, False otherwise
		"""

		if domains is None or not url:
			return True

		import fnmatch
		from urllib.parse import urlparse

		# Parse the URL to get the domain
		try:
			parsed_url = urlparse(url)
			if not parsed_url.netloc:
				return False

			domain = parsed_url.netloc
			# Remove port if present
			if ':' in domain:
				domain = domain.split(':')[0]

			for domain_pattern in domains:
				if fnmatch.fnmatch(domain, domain_pattern):  # Perform glob *.matching.*
					return True
			return False
		except Exception:
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
