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
    
    # Whether to use OmniParser only as a fallback when DOM extraction is insufficient
    use_as_fallback: bool = True
    
    # Minimum number of interactive elements expected in DOM extraction
    # If fewer elements are found, OmniParser will be used as fallback
    min_expected_elements: int = 1
    
    # Whether to use the hosted OmniParser API when local installation is not available
    use_api: bool = False
    
    # Custom endpoint for OmniParser service (optional)
    # If None, will use default based on use_api setting:
    # - Local server: "http://localhost:8000/screen/parse"
    # - Hosted API: "https://api.screenparse.ai/v1/screen/parse"
    endpoint: Optional[str] = None
    
    # API key for authentication with the OmniParser service (optional)
    # Required only if using an endpoint that needs authentication
    api_key: Optional[str] = None
    
    # List of required element types for LLM prediction
    # If specified and any of these elements are missing in DOM extraction,
    # OmniParser will be used as fallback
    required_elements: Optional[List[str]] = None
