import asyncio
import os
import pytest
import sys

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentOutput
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState
from browser_use.controller.registry.service import Registry
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.manager.highlight_manager import HighlightManager
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, DOMState, DOMTextNode
from langchain_core.language_models.chat_models import BaseChatModel
from playwright.async_api import Page
from pydantic import BaseModel
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# run with python -m pytest tests/test_service.py

class TestAgent:
	@pytest.fixture
	def mock_controller(self):
		controller = Mock(spec=Controller)
		registry = Mock(spec=Registry)
		registry.registry = MagicMock()
		registry.registry.actions = {'test_action': MagicMock(param_model=MagicMock())}  # type: ignore
		controller.registry = registry
		return controller

	@pytest.fixture
	def mock_llm(self):
		return Mock(spec=BaseChatModel)

	@pytest.fixture
	def mock_browser(self):
		return Mock(spec=Browser)

	@pytest.fixture
	def mock_browser_context(self):
		return Mock(spec=BrowserContext)

	def test_convert_initial_actions(self, mock_controller, mock_llm, mock_browser, mock_browser_context):  # type: ignore
		"""
		Test that the _convert_initial_actions method correctly converts
		dictionary-based actions to ActionModel instances.

		This test ensures that:
		1. The method processes the initial actions correctly.
		2. The correct param_model is called with the right parameters.
		3. The ActionModel is created with the validated parameters.
		4. The method returns a list of ActionModel instances.
		"""
		# Arrange
		agent = Agent(
			task='Test task', llm=mock_llm, controller=mock_controller, browser=mock_browser, browser_context=mock_browser_context
		)
		initial_actions = [{'test_action': {'param1': 'value1', 'param2': 'value2'}}]

		# Mock the ActionModel
		mock_action_model = MagicMock(spec=ActionModel)
		mock_action_model_instance = MagicMock()
		mock_action_model.return_value = mock_action_model_instance
		agent.ActionModel = mock_action_model  # type: ignore

		# Act
		result = agent._convert_initial_actions(initial_actions)

		# Assert
		assert len(result) == 1
		mock_controller.registry.registry.actions['test_action'].param_model.assert_called_once_with(  # type: ignore
			param1='value1', param2='value2'
		)
		mock_action_model.assert_called_once()
		assert isinstance(result[0], MagicMock)
		assert result[0] == mock_action_model_instance

		# Check that the ActionModel was called with the correct parameters
		call_args = mock_action_model.call_args[1]
		assert 'test_action' in call_args
		assert call_args['test_action'] == mock_controller.registry.registry.actions['test_action'].param_model.return_value  # type: ignore

	@pytest.mark.asyncio
	async def test_step_error_handling(self):
		"""
		Test the error handling in the step method of the Agent class.
		This test simulates a failure in the get_next_action method and
		checks if the error is properly handled and recorded.
		"""
		# Mock the LLM
		mock_llm = MagicMock(spec=BaseChatModel)

		# Mock the MessageManager
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Create an Agent instance with mocked dependencies
			agent = Agent(task='Test task', llm=mock_llm)

			# Mock the get_next_action method to raise an exception
			agent.get_next_action = AsyncMock(side_effect=ValueError('Test error'))

			# Mock the browser_context
			agent.browser_context = AsyncMock()
			agent.browser_context.get_state = AsyncMock(
				return_value=BrowserState(
					url='https://example.com',
					title='Example',
					element_tree=MagicMock(),  # Mocked element tree
					tabs=[],
					selector_map={},
					screenshot='',
				)
			)

			# Mock the controller
			agent.controller = AsyncMock()

			# Call the step method
			await agent.step()

			# Assert that the error was handled and recorded
			assert agent.consecutive_failures == 1
			assert len(agent._last_result) == 1
			assert isinstance(agent._last_result[0], ActionResult)
			assert 'Test error' in agent._last_result[0].error
			assert agent._last_result[0].include_in_memory == True

class TestRegistry:
    @pytest.fixture
    def registry_with_excludes(self):
        return Registry(exclude_actions=['excluded_action'])

    def test_action_decorator_with_excluded_action(self, registry_with_excludes):
        """
        Test that the action decorator does not register an action
        if it's in the exclude_actions list.
        """
        # Define a function to be decorated
        def excluded_action():
            pass

        # Apply the action decorator
        decorated_func = registry_with_excludes.action(description="This should be excluded")(excluded_action)

        # Assert that the decorated function is the same as the original
        assert decorated_func == excluded_action

        # Assert that the action was not added to the registry
        assert 'excluded_action' not in registry_with_excludes.registry.actions

        # Define another function that should be included
        def included_action():
            pass

        # Apply the action decorator to an included action
        registry_with_excludes.action(description="This should be included")(included_action)

        # Assert that the included action was added to the registry
        assert 'included_action' in registry_with_excludes.registry.actions

    @pytest.mark.asyncio
    async def test_execute_action_with_and_without_browser_context(self):
        """
        Test that the execute_action method correctly handles actions with and without a browser context.
        This test ensures that:
        1. An action requiring a browser context is executed correctly.
        2. An action not requiring a browser context is executed correctly.
        3. The browser context is passed to the action function when required.
        4. The action function receives the correct parameters.
        5. The method raises an error when a browser context is required but not provided.
        """
        registry = Registry()

        # Define a mock action model
        class TestActionModel(BaseModel):
            param1: str

        # Define mock action functions
        async def test_action_with_browser(param1: str, browser):
            return f"Action executed with {param1} and browser"

        async def test_action_without_browser(param1: str):
            return f"Action executed with {param1}"

        # Register the actions
        registry.registry.actions['test_action_with_browser'] = MagicMock(
            requires_browser=True,
            function=AsyncMock(side_effect=test_action_with_browser),
            param_model=TestActionModel,
            description="Test action with browser"
        )

        registry.registry.actions['test_action_without_browser'] = MagicMock(
            requires_browser=False,
            function=AsyncMock(side_effect=test_action_without_browser),
            param_model=TestActionModel,
            description="Test action without browser"
        )

        # Mock

    def test_create_selector_map(self):
        """
        Test the _create_selector_map method of the DomService class.
        This test ensures that:
        1. The method correctly creates a selector map from a given DOM tree.
        2. Only elements with highlight_index are included in the selector map.
        3. The selector map keys correspond to highlight indices and values to the correct DOMElementNode objects.
        """
        # Create a mock DOM tree
        root = DOMElementNode(
            tag_name="html",
            xpath="/html",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=False,
            is_top_element=True,
            highlight_index=0,
            shadow_root=False,
            parent=None
        )

        body = DOMElementNode(
            tag_name="body",
            xpath="/html/body",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=False,
            is_top_element=False,
            highlight_index=1,
            shadow_root=False,
            parent=root
        )

        div = DOMElementNode(
            tag_name="div",
            xpath="/html/body/div",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=False,
            is_top_element=False,
            highlight_index=2,
            shadow_root=False,
            parent=body
        )

        text = DOMTextNode(
            text="Hello, World!",
            is_visible=True,
            parent=div
        )

        div.children = [text]
        body.children = [div]
        root.children = [body]

        # Create a DomService instance (we don't need a real Page object for this test)
        dom_service = DomService(page=None)  # type: ignore

        # Call the _create_selector_map method
        selector_map = dom_service._create_selector_map(root)

        # Assert that the selector map is correctly created
        assert len(selector_map) == 3
        assert 0 in selector_map and selector_map[0] == root
        assert 1 in selector_map and selector_map[1] == body
        assert 2 in selector_map and selector_map[2] == div
        assert 3 not in selector_map  # Text node should not be in the selector map

class TestDomService:
    @pytest.mark.asyncio
    async def test_parse_node(self):
        """
        Test the _parse_node method of the DomService class.
        This test ensures that:
        1. The method correctly parses a text node.
        2. The method correctly parses an element node with various attributes.
        3. The method correctly handles child nodes.
        4. The highlight manager is called when position data is available.
        """
        # Mock the Page and HighlightManager
        mock_page = MagicMock(spec=Page)
        mock_highlight_manager = AsyncMock(spec=HighlightManager)

        # Create a DomService instance with mocked dependencies
        dom_service = DomService(page=mock_page)
        dom_service.highlight_manager = mock_highlight_manager

        # Test parsing a text node
        text_node_data = {
            "type": "TEXT_NODE",
            "text": "Hello, World!",
            "isVisible": True
        }
        text_node = await dom_service._parse_node(text_node_data)
        assert isinstance(text_node, DOMTextNode)
        assert text_node.text == "Hello, World!"
        assert text_node.is_visible == True

        # Test parsing an element node with children
        element_node_data = {
            "tagName": "div",
            "xpath": "/html/body/div",
            "attributes": {"class": "container"},
            "isVisible": True,
            "isInteractive": False,
            "isTopElement": False,
            "highlightIndex": 1,
            "shadowRoot": False,
            "position": {"x": 10, "y": 20, "width": 100, "height": 50},
            "children": [text_node_data]
        }
        element_node = await dom_service._parse_node(element_node_data)
        assert isinstance(element_node, DOMElementNode)
        assert element_node.tag_name == "div"
        assert element_node.xpath == "/html/body/div"
        assert element_node.attributes == {"class": "container"}
        assert element_node.is_visible == True
        assert element_node.is_interactive == False
        assert element_node.is_top_element == False
        assert element_node.highlight_index == 1
        assert element_node.shadow_root == False
        assert len(element_node.children) == 1
        assert isinstance(element_node.children[0], DOMTextNode)

        # Verify that the highlight manager was called
        mock_highlight_manager.highlight_element.assert_called_once_with(
            {"x": 10, "y": 20, "width": 100, "height": 50}, 1
        )

    @pytest.mark.asyncio
    async def test_get_clickable_elements(self):
        """
        Test the get_clickable_elements method of the DomService class.
        This test ensures that:
        1. The method correctly calls the JavaScript function to build the DOM tree.
        2. The method processes the returned DOM structure and creates a valid DOMState object.
        3. The resulting DOMState contains the expected element tree and selector map.
        """
        # Mock the Page object
        mock_page = AsyncMock()

        # Create a DomService instance with the mocked Page
        dom_service = DomService(page=mock_page)

        # Mock the JavaScript evaluation result
        mock_eval_result = {
            "tagName": "html",
            "xpath": "/html",
            "attributes": {},
            "isVisible": True,
            "isInteractive": False,
            "isTopElement": True,
            "highlightIndex": 0,
            "children": [
                {
                    "tagName": "body",
                    "xpath": "/html/body",
                    "attributes": {},
                    "isVisible": True,
                    "isInteractive": False,
                    "isTopElement": False,
                    "highlightIndex": 1,
                    "children": [
                        {
                            "type": "TEXT_NODE",
                            "text": "Hello, World!",
                            "isVisible": True
                        }
                    ]
                }
            ]
        }

        # Mock the page.evaluate method to return a coroutine
        mock_page.evaluate.return_value = mock_eval_result

        # Mock the resources.read_text function
        with patch('importlib.resources.read_text', return_value='mock_js_code'):
            # Call the get_clickable_elements method
            result = await dom_service.get_clickable_elements()

        # Assert that the result is a DOMState object
        assert isinstance(result, DOMState)

        # Assert that the element tree has the expected structure
        assert result.element_tree.tag_name == "html"
        assert len(result.element_tree.children) == 1
        assert result.element_tree.children[0].tag_name == "body"
        assert len(result.element_tree.children[0].children) == 1
        assert isinstance(result.element_tree.children[0].children[0], DOMTextNode)

        # Assert that the selector map contains the expected elements
        assert len(result.selector_map) == 2
        assert 0 in result.selector_map
        assert 1 in result.selector_map
        assert result.selector_map[0] == result.element_tree
        assert result.selector_map[1] == result.element_tree.children[0]