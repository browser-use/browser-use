"""
Configuration classes for the browser module.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from browser_use.omniparser.views import OmniParserSettings


@dataclass
class BrowserExtractionConfig:
    """Configuration for browser extraction strategies."""
    
    # OmniParser configuration
    omniparser: OmniParserSettings = field(default_factory=OmniParserSettings)
    
    # Whether to use hybrid extraction (combining DOM and OmniParser)
    use_hybrid_extraction: bool = False
