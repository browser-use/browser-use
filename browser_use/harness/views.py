"""Pydantic views for the harness-backed agent."""

from pydantic import BaseModel, ConfigDict

from browser_use.browser.views import TabInfo


class HarnessElement(BaseModel):
	"""One interactive element from the accessibility tree, addressable by index."""

	model_config = ConfigDict(extra='forbid')

	index: int
	role: str
	name: str
	backend_node_id: int

	def prompt_line(self) -> str:
		return f'[{self.index}]<{self.role} {self.name!r}>'


class HarnessState(BaseModel):
	"""One step's observation: indexed AX elements, text excerpt, optional screenshot."""

	model_config = ConfigDict(extra='forbid')

	url: str = ''
	title: str = ''
	tabs: list[TabInfo] = []
	elements: list[HarnessElement] = []
	text_excerpt: str = ''
	screenshot_b64: str | None = None
	dialog: dict | None = None
	# mirrors browser_use's BrowserStateSummary.state_error: a model-visible
	# explanation when the page could not be observed
	state_error: str | None = None

	@property
	def selector_map(self) -> dict[int, HarnessElement]:
		return {el.index: el for el in self.elements}

	def elements_text(self) -> str:
		if not self.elements:
			return '(no interactive elements found)'
		return '\n'.join(el.prompt_line() for el in self.elements)
