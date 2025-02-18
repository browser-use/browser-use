from dataclasses import dataclass
from typing import Optional
from browser_use.browser.enums.click_status import ClickStatus

@dataclass
class ClickResult:
    status: ClickStatus
    message: Optional[str] = None
    download_path: Optional[str] = None
    navigated_url: Optional[str] = None