from typing import Dict, Any, Callable, Type, Optional

class ToolRegistry:
    """Registry for tools that can be used with browser-use."""
    
    _tools: Dict[str, Any] = {}
    
    @classmethod
    def register(cls, tool_name: str, tool_class: Any) -> None:
        """Register a tool with the registry."""
        cls._tools[tool_name] = tool_class
        
    @classmethod
    def get_tool(cls, tool_name: str) -> Optional[Any]:
        """Get a tool from the registry."""
        return cls._tools.get(tool_name)
        
    @classmethod
    def list_tools(cls) -> Dict[str, Any]:
        """List all registered tools."""
        return cls._tools.copy()
