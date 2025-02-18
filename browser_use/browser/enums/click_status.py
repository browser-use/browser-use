from enum import Enum

class ClickStatus(Enum):
    SUCCESS = "success"
    NAVIGATION_SUCCESS = "navigation_success"
    ERROR = "error"
    DOWNLOAD_SUCCESS = "download_success"
    NAVIGATION_DISALLOWED = "navigation_disallowed"
