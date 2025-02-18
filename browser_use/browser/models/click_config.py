from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ClickConfig:
    timeouts: Dict[str, int] = field(default_factory=lambda: {
        'click': 2000,
        'download': 5,
        'navigation': 5,
        'popup': 2000
    })
    max_retries: int = 1
    initial_retry_delay: float = 1.0
    save_downloads_path: Optional[str] = None