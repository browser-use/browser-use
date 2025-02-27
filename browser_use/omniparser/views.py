"""
View models for OmniParser integration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union


@dataclass
class OmniParserSettings:
    """Settings for OmniParser."""
    
    # Whether to use OmniParser for UI element detection
    enabled: bool = False
    
    # Confidence threshold for element detection (0.0 to 1.0)
    confidence_threshold: float = 0.5
    
    # Path to OmniParser model weights directory
    # If None, will use the default location
    weights_dir: Optional[str] = None
    
    # Whether to prefer OmniParser results over DOM-based results
    # when both are available
    prefer_over_dom: bool = False
    
    # Whether to use OmniParser for CAPTCHA detection specifically
    captcha_detection: bool = True
    
    # Whether to merge OmniParser results with DOM-based results
    merge_with_dom: bool = True
    
    # Whether to use the hosted OmniParser API when local installation is not available
    use_api: bool = False
    
    # API key for the hosted OmniParser service
    api_key: Optional[str] = None
