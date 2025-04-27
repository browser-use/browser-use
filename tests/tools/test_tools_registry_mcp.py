import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from browser_use.tools.registry import ToolRegistry  # noqa: E402
from browser_use.tools.mcp_protocol import MCPToolBase  # noqa: E402


class TestToolsRegistryMCP(unittest.TestCase):
    """Test the tools registry with MCP support."""

    def setUp(self):
        """Set up the test environment."""
        ToolRegistry._tools = {}
        ToolRegistry._capabilities_index = {}

        class TestTool1(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return {"success": True, "result": "test1"}
            
            def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
                capabilities = ["can_test", "can_demo"]
                if context.get("special", False):
                    capabilities.append("can_special")
                return capabilities

        class TestTool2(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return {"success": True, "result": "test2"}
            
            def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
                return ["can_other", "can_demo"]

        class LegacyTool:
            def process(self, data):
                return f"Processed: {data}"

        self.TestTool1 = TestTool1
        self.TestTool2 = TestTool2
        self.LegacyTool = LegacyTool

    def test_register_and_get_tool(self):
        """Test registering and retrieving tools."""
        ToolRegistry.register("test_tool1", self.TestTool1)
        ToolRegistry.register("test_tool2", self.TestTool2)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        tool1_class = ToolRegistry.get_tool("test_tool1")
        tool2_class = ToolRegistry.get_tool("test_tool2")
        legacy_tool_class = ToolRegistry.get_tool("legacy_tool")

        self.assertEqual(tool1_class, self.TestTool1)
        self.assertEqual(tool2_class, self.TestTool2)
        self.assertEqual(legacy_tool_class, self.LegacyTool)

    def test_list_tools(self):
        """Test listing all registered tools."""
        ToolRegistry.register("test_tool1", self.TestTool1)
        ToolRegistry.register("test_tool2", self.TestTool2)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        tools = ToolRegistry.list_tools()

        self.assertEqual(len(tools), 3)
        self.assertIn("test_tool1", tools)
        self.assertIn("test_tool2", tools)
        self.assertIn("legacy_tool", tools)
        self.assertEqual(tools["test_tool1"], self.TestTool1)
        self.assertEqual(tools["test_tool2"], self.TestTool2)
        self.assertEqual(tools["legacy_tool"], self.LegacyTool)

    def test_get_tools_by_capability(self):
        """Test getting tools by capability."""
        ToolRegistry.register("test_tool1", self.TestTool1)
        ToolRegistry.register("test_tool2", self.TestTool2)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        test_tools = ToolRegistry.get_tools_by_capability("can_test", {})
        demo_tools = ToolRegistry.get_tools_by_capability("can_demo", {})
        other_tools = ToolRegistry.get_tools_by_capability("can_other", {})
        special_tools = ToolRegistry.get_tools_by_capability("can_special", {"special": True})
        nonexistent_tools = ToolRegistry.get_tools_by_capability("can_nonexistent", {})

        self.assertEqual(len(test_tools), 1)
        self.assertIn("test_tool1", test_tools)

        self.assertEqual(len(demo_tools), 2)
        self.assertIn("test_tool1", demo_tools)
        self.assertIn("test_tool2", demo_tools)

        self.assertEqual(len(other_tools), 1)
        self.assertIn("test_tool2", other_tools)

        self.assertEqual(len(special_tools), 1)
        self.assertIn("test_tool1", special_tools)

        self.assertEqual(len(nonexistent_tools), 0)

    def test_get_tool_metadata(self):
        """Test getting tool metadata."""
        ToolRegistry.register("test_tool1", self.TestTool1)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        tool1_metadata = ToolRegistry.get_tool_metadata("test_tool1")
        legacy_tool_metadata = ToolRegistry.get_tool_metadata("legacy_tool")
        nonexistent_tool_metadata = ToolRegistry.get_tool_metadata("nonexistent_tool")

        self.assertIsNotNone(tool1_metadata)
        self.assertEqual(tool1_metadata["name"], "test_tool1")
        self.assertIn("description", tool1_metadata)
        self.assertIn("parameters", tool1_metadata)
        self.assertIn("returns", tool1_metadata)
        self.assertIn("version", tool1_metadata)

        self.assertIsNotNone(legacy_tool_metadata)
        self.assertEqual(legacy_tool_metadata["name"], "legacy_tool")
        self.assertIn("description", legacy_tool_metadata)
        self.assertTrue(legacy_tool_metadata["legacy"])

        self.assertIsNone(nonexistent_tool_metadata)

    def test_get_all_capabilities(self):
        """Test getting all capabilities."""
        ToolRegistry.register("test_tool1", self.TestTool1)
        ToolRegistry.register("test_tool2", self.TestTool2)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        capabilities = ToolRegistry.get_all_capabilities({})
        special_capabilities = ToolRegistry.get_all_capabilities({"special": True})

        self.assertEqual(len(capabilities), 3)
        self.assertIn("can_test", capabilities)
        self.assertIn("can_demo", capabilities)
        self.assertIn("can_other", capabilities)

        self.assertEqual(len(special_capabilities), 4)
        self.assertIn("can_special", special_capabilities)

    def test_get_tool_examples(self):
        """Test getting tool examples."""
        class ToolWithExamples(MCPToolBase):
            def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return {"success": True, "result": "test"}
            
            def get_examples(self) -> List[Dict[str, Any]]:
                return [
                    {
                        "description": "Example 1",
                        "params": {"param1": "value1"},
                        "context": {"context1": "value1"},
                        "expected_result": {"success": True, "result": "test"}
                    }
                ]

        ToolRegistry.register("tool_with_examples", ToolWithExamples)
        ToolRegistry.register("legacy_tool", self.LegacyTool)

        examples = ToolRegistry.get_tool_examples("tool_with_examples")
        legacy_examples = ToolRegistry.get_tool_examples("legacy_tool")
        nonexistent_examples = ToolRegistry.get_tool_examples("nonexistent_tool")

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["description"], "Example 1")
        self.assertEqual(examples[0]["params"], {"param1": "value1"})
        self.assertEqual(examples[0]["context"], {"context1": "value1"})
        self.assertEqual(examples[0]["expected_result"], {"success": True, "result": "test"})

        self.assertEqual(len(legacy_examples), 0)

        self.assertEqual(len(nonexistent_examples), 0)


if __name__ == "__main__":
    unittest.main()
