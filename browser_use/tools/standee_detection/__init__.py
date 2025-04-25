from .standee_detector import StandeeDetectionTool
from ..registry import ToolRegistry

ToolRegistry.register('standee_detection', StandeeDetectionTool)
