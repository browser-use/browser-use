import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from browser_use.tools.mcp_protocol import MCPToolProtocol, MCPToolBase  # noqa: E402


class TestMCPProtocol(unittest.TestCase):
    """Test the MCP protocol implementation."""

    def test_mcp_tool_protocol_interface(self):
        """Test that the MCPToolProtocol defines the required methods."""
        self.assertTrue(hasattr(MCPToolProtocol, 'metadata'))
        self.assertTrue(hasattr(MCPToolProtocol, 'get_capabilities'))
        self.assertTrue(hasattr(MCPToolProtocol, 'execute'))
        self.assertTrue(hasattr(MCPToolProtocol, 'get_examples'))

    def test_mcp_tool_base_implementation(self):
        """Test that the MCPToolBase implements the protocol correctly."""
        class TestTool(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return {"success": True, "result": "test"}

        tool = TestTool(name="test_tool", description="A test tool")

        self.assertTrue(hasattr(tool, 'metadata'))
        self.assertTrue(hasattr(tool, 'get_capabilities'))
        self.assertTrue(hasattr(tool, 'execute'))
        self.assertTrue(hasattr(tool, 'get_examples'))

        metadata = tool.metadata
        self.assertEqual(metadata["name"], "test_tool")
        self.assertEqual(metadata["description"], "A test tool")
        self.assertIn("parameters", metadata)
        self.assertIn("returns", metadata)
        self.assertIn("version", metadata)

        capabilities = tool.get_capabilities({})
        self.assertIsInstance(capabilities, list)
        self.assertIn("can_test_tool", capabilities)

        examples = tool.get_examples()
        self.assertIsInstance(examples, list)

        result = tool.execute({}, {})
        self.assertEqual(result["success"], True)
        self.assertEqual(result["result"], "test")

    def test_format_success_result(self):
        """Test the format_success_result method."""
        class TestTool(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return self.format_success_result("test result")

        tool = TestTool(name="test_tool", description="A test tool")

        result = tool.format_success_result("test result")
        self.assertEqual(result["success"], True)
        self.assertEqual(result["result"], "test result")
        self.assertEqual(result["metadata"], {})

        result = tool.format_success_result("test result", {"extra": "info"})
        self.assertEqual(result["success"], True)
        self.assertEqual(result["result"], "test result")
        self.assertEqual(result["metadata"], {"extra": "info"})

    def test_format_error_result(self):
        """Test the format_error_result method."""
        class TestTool(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return self.format_error_result("test error")

        tool = TestTool(name="test_tool", description="A test tool")

        result = tool.format_error_result("test error")
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "test error")
        self.assertEqual(result["metadata"], {})

        result = tool.format_error_result(ValueError("test exception"))
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "test exception")
        self.assertEqual(result["metadata"], {})

        result = tool.format_error_result("test error", {"extra": "info"})
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "test error")
        self.assertEqual(result["metadata"], {"extra": "info"})


if __name__ == "__main__":
    unittest.main()
