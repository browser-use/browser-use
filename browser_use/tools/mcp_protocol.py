"""
Model Context Protocol (MCP) for browser-use tools.

This module defines the protocol for tools that follow the Model Context Protocol,
which enables tools to be more discoverable and usable by LLMs.
"""

from typing import Dict, List, Any, Optional, Union


class MCPToolProtocol:
    """
    Protocol for tools that follow the Model Context Protocol.
    
    Tools implementing this protocol provide rich metadata about their capabilities,
    adapt to the current context, and provide structured feedback about their execution.
    """
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Return tool metadata including name, description, parameters, and returns.
        
        Returns:
            Dict with the following keys:
                - name: Tool name
                - description: Detailed description of the tool
                - parameters: Dict of parameter names to parameter metadata
                - returns: Dict describing the return value structure
                - version: Tool version
        """
        raise NotImplementedError("Tool must implement metadata property")
    
    def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
        """
        Return capabilities based on current context.
        
        Args:
            context: Current execution context
            
        Returns:
            List of capability strings that this tool provides in the given context
        """
        raise NotImplementedError("Tool must implement get_capabilities method")
    
    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tool with parameters and context, return structured results.
        
        Args:
            params: Parameters for tool execution
            context: Current execution context
            
        Returns:
            Dict with the following keys:
                - success: Boolean indicating success or failure
                - result: Result data (if success is True)
                - error: Error message (if success is False)
                - metadata: Additional metadata about the execution
        """
        raise NotImplementedError("Tool must implement execute method")
    
    def get_examples(self) -> List[Dict[str, Any]]:
        """
        Return usage examples with inputs and expected outputs.
        
        Returns:
            List of example dicts, each with:
                - description: Example description
                - params: Example parameters
                - context: Example context
                - expected_result: Expected result
        """
        raise NotImplementedError("Tool must implement get_examples method")


class MCPToolBase(MCPToolProtocol):
    """
    Base class for tools implementing the Model Context Protocol.
    
    Provides default implementations for some methods and utility functions
    for working with MCP tools.
    """
    
    def __init__(self, name: str, description: str):
        """
        Initialize the MCP tool.
        
        Args:
            name: Tool name
            description: Tool description
        """
        self._name = name
        self._description = description
        self._version = "1.0.0"
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Return tool metadata.
        
        Returns:
            Dict with tool metadata
        """
        return {
            "name": self._name,
            "description": self._description,
            "parameters": self._get_parameter_metadata(),
            "returns": self._get_return_metadata(),
            "version": self._version
        }
    
    def _get_parameter_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        Return metadata about tool parameters.
        
        Returns:
            Dict mapping parameter names to parameter metadata
        """
        return {}
    
    def _get_return_metadata(self) -> Dict[str, Any]:
        """
        Return metadata about tool return values.
        
        Returns:
            Dict describing the return value structure
        """
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Whether the tool execution was successful"
                },
                "result": {
                    "type": "object",
                    "description": "Result data if execution was successful"
                },
                "error": {
                    "type": "string",
                    "description": "Error message if execution failed"
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional metadata about the execution"
                }
            }
        }
    
    def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
        """
        Return capabilities based on current context.
        
        Args:
            context: Current execution context
            
        Returns:
            List of capability strings
        """
        return [f"can_{self._name.lower().replace(' ', '_')}"]
    
    def get_examples(self) -> List[Dict[str, Any]]:
        """
        Return usage examples.
        
        Returns:
            List of example dicts
        """
        return []
    
    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tool with parameters and context.
        
        Args:
            params: Parameters for tool execution
            context: Current execution context
            
        Returns:
            Dict with execution results
        """
        raise NotImplementedError("Tool must implement execute method")
    
    def format_success_result(self, result: Any, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Format a successful result.
        
        Args:
            result: Result data
            metadata: Additional metadata
            
        Returns:
            Formatted result dict
        """
        return {
            "success": True,
            "result": result,
            "metadata": metadata or {}
        }
    
    def format_error_result(self, error: Union[str, Exception], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Format an error result.
        
        Args:
            error: Error message or exception
            metadata: Additional metadata
            
        Returns:
            Formatted error dict
        """
        error_message = str(error)
        return {
            "success": False,
            "error": error_message,
            "metadata": metadata or {}
        }
