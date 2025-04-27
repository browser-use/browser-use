import sys
import unittest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any, ClassVar

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from browser_use.agent.service import Agent  # noqa: E402
from browser_use.tools.registry import ToolRegistry  # noqa: E402
from browser_use.tools.mcp_protocol import MCPToolBase  # noqa: E402


class TestAgentMCPIntegration(unittest.TestCase):
    """Test the integration of MCP tools with the Agent."""

    def setUp(self):
        """Set up the test environment."""
        self.create_task_patcher = patch('asyncio.create_task', return_value=MagicMock())
        self.mock_create_task = self.create_task_patcher.start()
        
        class MockBaseChatModel(BaseChatModel):
            model_name: ClassVar[str] = "mock_model"
            
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return AIMessage(content='{"action": [], "current_state": {"evaluation_previous_goal": "", "memory": "", "next_goal": ""}}')
            
            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop, run_manager, **kwargs)
            
            @property
            def _llm_type(self):
                return "mock_llm"
        
        self.MockBaseChatModel = MockBaseChatModel
        
        class MockTool(MCPToolBase):
            def __init__(self):
                super().__init__(name="mock_tool", description="A mock tool for testing")
                self.execute_called = False
                self.execute_params = None
                self.execute_context = None
            
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                self.execute_called = True
                self.execute_params = params
                self.execute_context = context
                return {"success": True, "result": "mock result"}
            
            def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
                if context.get("special", False):
                    return ["can_mock", "can_special"]
                return ["can_mock"]

        self.MockTool = MockTool
        
        ToolRegistry._tools = {}
        ToolRegistry._capabilities_index = {}
        ToolRegistry.register("mock_tool", self.MockTool)
        
    def tearDown(self):
        """Clean up after tests."""
        self.create_task_patcher.stop()

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_tool_initialization(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent initializes tools correctly."""
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test task",
            llm=mock_llm,
            tools=["mock_tool"]
        )
        
        self.assertIn("mock_tool", agent.tools)
        self.assertIsInstance(agent.tools["mock_tool"], self.MockTool)

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_get_tool(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent can retrieve tools."""
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test task",
            llm=mock_llm,
            tools=["mock_tool"]
        )
        
        tool = agent.get_tool("mock_tool")
        
        self.assertIsNotNone(tool)
        self.assertIsInstance(tool, self.MockTool)
        
        nonexistent_tool = agent.get_tool("nonexistent_tool")
        
        self.assertIsNone(nonexistent_tool)

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_get_tool_capabilities(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent can get tool capabilities."""
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test task",
            llm=mock_llm,
            tools=["mock_tool"]
        )
        
        capabilities = agent.get_tool_capabilities({})
        
        self.assertIn("mock_tool", capabilities)
        self.assertIn("can_mock", capabilities["mock_tool"])
        
        special_capabilities = agent.get_tool_capabilities({"special": True})
        
        self.assertIn("can_special", special_capabilities["mock_tool"])

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_get_tool_metadata(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent can get tool metadata."""
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test task",
            llm=mock_llm,
            tools=["mock_tool"]
        )
        
        metadata = agent.get_tool_metadata("mock_tool")
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["name"], "mock_tool")
        self.assertEqual(metadata["description"], "A mock tool for testing")
        self.assertIn("parameters", metadata)
        self.assertIn("returns", metadata)
        self.assertIn("version", metadata)
        
        nonexistent_metadata = agent.get_tool_metadata("nonexistent_tool")
        
        self.assertIsNone(nonexistent_metadata)

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_execute_tool(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent can execute tools."""
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test task",
            llm=mock_llm,
            tools=["mock_tool"]
        )
        
        params = {"param1": "value1"}
        context = {"context1": "value1"}
        result = agent.execute_tool("mock_tool", params, context)
        
        tool = agent.get_tool("mock_tool")
        self.assertTrue(tool.execute_called)
        self.assertEqual(tool.execute_params, params)
        self.assertEqual(tool.execute_context, context)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "mock result")
        
        nonexistent_result = agent.execute_tool("nonexistent_tool", {}, {})
        
        self.assertFalse(nonexistent_result["success"])
        self.assertIn("error", nonexistent_result)

    @patch('browser_use.agent.service.Browser')
    @patch('browser_use.agent.service.Controller')
    @patch('browser_use.agent.service.MessageManager')
    def test_agent_execute_tool_method(self, mock_message_manager, mock_controller, mock_browser):
        """Test that the agent can execute tool methods."""
        class ToolWithMethod(MCPToolBase):
            def __init__(self):
                super().__init__(name="tool_with_method", description="A tool with a method")
                self.method_called = False
                self.method_param = None
            
            def test_method(self, param):
                self.method_called = True
                self.method_param = param
                return f"Method result: {param}"
            
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                if params.get("method") == "test_method":
                    result = self.test_method(params.get("params", {}).get("param"))
                    return {"success": True, "result": result}
                return {"success": False, "error": "Invalid method"}

        ToolRegistry.register("tool_with_method", ToolWithMethod)
        
        mock_llm = self.MockBaseChatModel()
        
        agent = Agent(
            task="Test tool method execution",
            llm=mock_llm,
            tools=["tool_with_method"]
        )
        
        result = agent.execute_tool("tool_with_method", {
            "method": "test_method",
            "params": {"param": "test_value"}
        }, {})
        
        tool = agent.get_tool("tool_with_method")
        self.assertTrue(tool.method_called)
        self.assertEqual(tool.method_param, "test_value")
        
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "Method result: test_value")


if __name__ == "__main__":
    unittest.main()
