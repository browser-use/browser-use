"""Safari real-profile backend support."""

from .capabilities import SafariCapabilityReport, probe_safari_environment
from .profiles import SafariProfileBinding, SafariProfileStore
from .session import SafariBrowserSession

__all__ = [
	'SafariBrowserSession',
	'SafariCapabilityReport',
	'SafariProfileBinding',
	'SafariProfileStore',
	'probe_safari_environment',
]
