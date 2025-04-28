from typing import Dict, Any, Optional, List, Set
from .mcp_protocol import MCPToolBase


class ToolRegistry:
    """
    Registry for tools that can be used with browser-use.

    Supports both legacy tools and tools that implement the Model Context Protocol (MCP).
    """

    _tools: Dict[str, Any] = {}
    _capabilities_index: Dict[str, Set[str]] = {}

    @classmethod
    def register(cls, tool_name: str, tool_class: Any) -> None:
        """
        Register a tool with the registry.

        Args:
            tool_name: Name of the tool
            tool_class: Tool class or constructor
        """
        cls._tools[tool_name] = tool_class

        if hasattr(
                tool_class,
                'get_capabilities') and callable(
                tool_class.get_capabilities):
            pass

    @classmethod
    def get_tool(cls, tool_name: str) -> Optional[Any]:
        """
        Get a tool from the registry.

        Args:
            tool_name: Name of the tool to retrieve

        Returns:
            The tool class or constructor, or None if not found
        """
        return cls._tools.get(tool_name)

    @classmethod
    def list_tools(cls) -> List[str]:
        """
        List all registered tools.

        Returns:
            List of registered tool names
        """
        return list(cls._tools.keys())

    @classmethod
    def get_tools_by_capability(
            cls, capability: str, context: Dict[str, Any]) -> List[str]:
        """
        Get tools that provide a specific capability in the given context.

        Args:
            capability: Capability to look for
            context: Current execution context

        Returns:
            List of tool names that provide the capability
        """
        matching_tools = []

        for tool_name, tool_class in cls._tools.items():
            if hasattr(
                    tool_class,
                    'get_capabilities') and callable(
                    tool_class.get_capabilities):
                if isinstance(tool_class, type):
                    if issubclass(tool_class, MCPToolBase):
                        tool = tool_class(name=tool_name, description=getattr(tool_class, "__doc__", ""))
                    else:
                        tool = tool_class()
                else:
                    tool = tool_class

                if capability in tool.get_capabilities(context):
                    matching_tools.append(tool_name)

        return matching_tools

    @classmethod
    def get_tool_metadata(cls, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool metadata dict, or None if the tool doesn't implement MCP
        """
        tool_class = cls.get_tool(tool_name)
        if not tool_class:
            return None

        if hasattr(
                tool_class,
                'metadata') and (
                callable(
                tool_class.metadata) or isinstance(
                    tool_class.metadata,
                property)):
            if isinstance(tool_class, type):
                if issubclass(tool_class, MCPToolBase):
                    tool = tool_class(name=tool_name, description=getattr(tool_class, "__doc__", ""))
                else:
                    tool = tool_class()
            else:
                tool = tool_class

            return tool.metadata

        return {
            "name": tool_name,
            "description": getattr(
                tool_class,
                "__doc__",
                "No description available"),
            "legacy": True}

    @classmethod
    def get_all_capabilities(cls, context: Dict[str, Any]) -> List[str]:
        """
        Get all capabilities provided by registered tools in the given context.

        Args:
            context: Current execution context

        Returns:
            List of all capabilities
        """
        all_capabilities = set()

        for tool_name, tool_class in cls._tools.items():
            if hasattr(
                    tool_class,
                    'get_capabilities') and callable(
                    tool_class.get_capabilities):
                if isinstance(tool_class, type):
                    if issubclass(tool_class, MCPToolBase):
                        tool = tool_class(name=tool_name, description=getattr(tool_class, "__doc__", ""))
                    else:
                        tool = tool_class()
                else:
                    tool = tool_class

                all_capabilities.update(tool.get_capabilities(context))

        return sorted(list(all_capabilities))

    @classmethod
    def get_tool_examples(cls, tool_name: str) -> List[Dict[str, Any]]:
        """
        Get usage examples for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of example dicts, or empty list if the tool doesn't implement MCP
        """
        tool_class = cls.get_tool(tool_name)
        if not tool_class:
            return []

        if hasattr(
                tool_class,
                'get_examples') and callable(
                tool_class.get_examples):
            if isinstance(tool_class, type):
                if issubclass(tool_class, MCPToolBase):
                    tool = tool_class(name=tool_name, description=getattr(tool_class, "__doc__", ""))
                else:
                    tool = tool_class()
            else:
                tool = tool_class

            return tool.get_examples()

        return []
