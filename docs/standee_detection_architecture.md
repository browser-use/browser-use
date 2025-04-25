# Standee Detection Tool Architecture

## Overview

The standee detection tool integration provides a modular, decoupled approach for the LLM agent to detect standees in images. This architecture ensures that the tool can be dynamically called by the LLM based on the context of the task, without being tightly coupled to specific navigation flows like carousel navigation.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                       Browser-Use Library                       │
│                                                                 │
│  ┌───────────────┐       ┌───────────────┐      ┌────────────┐  │
│  │               │       │               │      │            │  │
│  │  ToolRegistry │◄──────┤  Agent Class  │◄─────┤    LLM     │  │
│  │               │       │               │      │            │  │
│  └───────┬───────┘       └───────┬───────┘      └────────────┘  │
│          │                       │                              │
│          │                       │                              │
│          ▼                       ▼                              │
│  ┌───────────────┐       ┌───────────────┐                     │
│  │               │       │               │                     │
│  │ Standee Tool  │◄──────┤  get_tool()   │                     │
│  │               │       │               │                     │
│  └───────┬───────┘       └───────────────┘                     │
│          │                                                     │
│          │                                                     │
│          ▼                                                     │
│  ┌───────────────┐                                             │
│  │               │                                             │
│  │  YOLOv8 Model │                                             │
│  │               │                                             │
│  └───────────────┘                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### ToolRegistry

The `ToolRegistry` is a central registry that stores all available tools by name. It provides methods to register, retrieve, and list tools.

```python
class ToolRegistry:
    _tools: Dict[str, Any] = {}

    @classmethod
    def register(cls, tool_name: str, tool_class: Any) -> None:
        cls._tools[tool_name] = tool_class

    @classmethod
    def get_tool(cls, tool_name: str) -> Optional[Any]:
        return cls._tools.get(tool_name)
```

### Agent Class

The `Agent` class is enhanced to support tool initialization and retrieval. It initializes tools from the registry based on the tool names provided during initialization.

```python
class Agent:
    def __init__(self, ..., tools: Optional[List[str]] = None):
        # Initialize tools
        self.tools = {}
        if tools:
            for tool_name in tools:
                tool_class = ToolRegistry.get_tool(tool_name)
                if tool_class:
                    self.tools[tool_name] = tool_class()
                    
    def get_tool(self, tool_name: str) -> Optional[Any]:
        return self.tools.get(tool_name)
```

### StandeeDetectionTool

The `StandeeDetectionTool` implements the standee detection functionality. It provides methods to detect standees in images from URLs or bytes.

```python
class StandeeDetectionTool:
    def __init__(self, model_path: Optional[str] = None, confidence_threshold: float = 0.25):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        
    def detect_from_url(self, image_url: str) -> Dict[str, Any]:
        # Implementation details...
        
    def detect_from_bytes(self, image_bytes: bytes) -> Dict[str, Any]:
        # Implementation details...
```

### System Prompt

The system prompt contains instructions for the LLM on how to use the tools. It provides clear guidance on when and how to use the standee detection tool.

```python
STANDEE_DETECTION_SYSTEM_PROMPT = """
When working with the standee detection tool:
- Access the tool using agent.get_tool('standee_detection')
- For each photo URL, call detector.detect_from_url(photo_url)
- Check the 'success' field in the result to verify detection ran properly
- Check the 'detections' array for any detected standees
- Log positive detections with confidence scores
"""
```

## Flow Diagram

```
┌─────────┐     ┌─────────────┐     ┌───────────────┐
│         │     │             │     │               │
│   LLM   │────►│ Agent Class │────►│ get_tool()    │
│         │     │             │     │               │
└─────────┘     └─────────────┘     └───────┬───────┘
                                            │
                                            │
                                            ▼
┌─────────────────┐     ┌───────────────────────────┐
│                 │     │                           │
│ Detection Result│◄────┤ StandeeDetectionTool      │
│                 │     │                           │
└─────────────────┘     └───────────────────────────┘
```

## Dynamic Tool Calling

The LLM dynamically decides when to use the tool based on the context of the task. This decoupled approach allows for more flexible and context-aware tool usage.

### Before (Coupled):

```python
async def process_photos(agent, photo_urls):
    for url in photo_urls:
        await process_photo_with_standee_detection(agent, url)
```

### After (Decoupled):

The LLM receives instructions in the system prompt:

```
You have access to a standee detection tool. You can use it like this:
detector = agent.get_tool('standee_detection')
result = detector.detect_from_url(photo_url)
```

The LLM then decides when to use the tool based on the context of the task:

```python
# LLM-generated code during task execution
detector = agent.get_tool('standee_detection')
result = detector.detect_from_url(photo_url)
if result['success'] and result['detections']:
    print(f"Found {len(result['detections'])} standees in {photo_url}")
```

## Benefits

1. **Decoupling**: The standee detection tool is decoupled from specific navigation flows
2. **Flexibility**: The LLM can decide when to use the tool based on the context
3. **Modularity**: New tools can be added to the registry without modifying existing code
4. **Reusability**: The same tool can be used in different contexts and tasks
5. **Testability**: Each component can be tested independently
