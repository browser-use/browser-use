"""Browser backend implementations."""

from .base import BackendCapabilityReport, BrowserBackend, BrowserBackendCapabilities
from .safari_backend import SafariRealProfileBackend

__all__ = [
	'BackendCapabilityReport',
	'BrowserBackend',
	'BrowserBackendCapabilities',
	'SafariRealProfileBackend',
]
