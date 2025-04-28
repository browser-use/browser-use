import sys
import unittest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any, ClassVar

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from browser_use.agent.service import Agent
from browser_use.tools.registry import ToolRegistry
from browser_use.tools.mcp_protocol import MCPToolBase


class MockTool(MCPToolBase):
    def __init__(self):
        super().__init__(name="mock_tool", description="A mock tool for testing")
        
    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "result": "mock result"}
        
    def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
        return ["can_mock"]


class MockBaseChatModel(BaseChatModel):
    model_name: ClassVar[str] = "mock_model"
    
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return AIMessage(content='{"action": [], "current_state": {"evaluation_previous_goal": "", "memory": "", "next_goal": ""}}')
    
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)
    
    @property
    def _llm_type(self):
        return "mock_llm"


class TestAgentDynamicToolDiscovery(unittest.TestCase):
    """Test the dynamic tool discovery in Agent."""

    def setUp(self):
        """Set up the test environment."""
        self.mock_llm = MockBaseChatModel()
        
        ToolRegistry._tools = {}
        ToolRegistry.register("mock_tool", MockTool)
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.create_task_patcher = patch('asyncio.create_task', 
                                         side_effect=lambda coro: self.loop.create_task(coro))
        self.mock_create_task = self.create_task_patcher.start()
        
        self.verify_llm_patcher = patch('browser_use.agent.service.Agent._verify_llm_connection', 
                                        return_value=None)
        self.mock_verify_llm = self.verify_llm_patcher.start()
        
    def tearDown(self):
        """Clean up after tests."""
        self.create_task_patcher.stop()
        self.verify_llm_patcher.stop()
        self.loop.close()
        
    def test_auto_tool_discovery(self):
        """Test that Agent automatically discovers tools when no tools parameter is provided."""
        with patch('browser_use.agent.service.Browser'), \
             patch('browser_use.agent.service.Controller'), \
             patch('browser_use.agent.service.MessageManager'), \
             patch('browser_use.agent.service.SystemPrompt') as mock_system_prompt:
            
            mock_system_prompt.return_value.get_system_message.return_value = SystemMessage(content="Mock system message")
            
            agent = Agent(
                task="Test task",
                llm=self.mock_llm,
                tools=None  # No tools specified
            )
            
            self.assertIn("mock_tool", agent.tools)
            self.assertIsInstance(agent.tools["mock_tool"], MockTool)
            
    def test_explicit_tool_specification(self):
        """Test that explicit tool specification still works."""
        with patch('browser_use.agent.service.Browser'), \
             patch('browser_use.agent.service.Controller'), \
             patch('browser_use.agent.service.MessageManager'), \
             patch('browser_use.agent.service.SystemPrompt') as mock_system_prompt:
            
            mock_system_prompt.return_value.get_system_message.return_value = SystemMessage(content="Mock system message")
            
            class AnotherMockTool(MCPToolBase):
                def __init__(self):
                    super().__init__(name="another_tool", description="Another mock tool")
            
            ToolRegistry.register("another_tool", AnotherMockTool)
            
            agent = Agent(
                task="Test task",
                llm=self.mock_llm,
                tools=["mock_tool"]  # Only specify one tool
            )
            
            self.assertIn("mock_tool", agent.tools)
            self.assertNotIn("another_tool", agent.tools)


if __name__ == "__main__":
    unittest.main()
