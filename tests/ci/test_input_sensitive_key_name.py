"""The input action must receive sensitive_data so it can name the key it typed instead of 'Typed sensitive data'."""

from unittest.mock import AsyncMock, MagicMock

from browser_use.browser.events import TypeTextEvent
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType
from browser_use.tools.service import Tools


class _CompletedEvent:
	def __await__(self):
		async def _done():
			return None

		return _done().__await__()

	async def event_result(self, **kwargs):
		return {}


def _password_node() -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='INPUT',
		node_value='',
		attributes={'type': 'password'},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=None,
	)


async def test_input_reports_which_sensitive_key_was_typed():
	dispatched: list[TypeTextEvent] = []
	browser_session = MagicMock()
	browser_session.get_element_by_index = AsyncMock(return_value=_password_node())
	browser_session.highlight_interaction_element = AsyncMock()
	browser_session.get_current_page_url = AsyncMock(return_value='https://example.com/login')
	browser_session.event_bus.dispatch = lambda event: dispatched.append(event) or _CompletedEvent()

	result = await Tools().registry.execute_action(
		'input',
		{'index': 1, 'text': 'hunter2'},
		browser_session=browser_session,
		sensitive_data={'x_password': 'hunter2'},
	)

	assert result.extracted_content == 'Typed x_password'
	assert 'hunter2' not in (result.extracted_content or '')
	assert len(dispatched) == 1
	assert dispatched[0].is_sensitive is True
	assert dispatched[0].sensitive_key_name == 'x_password'
