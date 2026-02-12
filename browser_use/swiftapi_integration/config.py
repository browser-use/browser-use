"""
SwiftAPI Configuration for Browser-Use Integration
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SwiftAPIConfig:
	"""Configuration for SwiftAPI integration with browser-use.

	Attributes:
	    api_key: SwiftAPI authority key (format: swiftapi_live_...)
	    base_url: SwiftAPI authority URL
	    app_id: Application identifier for attestation context
	    actor: Actor identifier (agent/user making requests)
	    timeout: Request timeout in seconds
	    paranoid_mode: Enable real-time revocation checks
	    fail_open: If True, allow actions when SwiftAPI is unreachable (NOT RECOMMENDED)
	    verbose: Print attestation status to console
	"""

	api_key: str | None = None
	base_url: str = 'https://swiftapi.ai'
	app_id: str = 'browser-use'
	actor: str = 'browser-use-agent'
	timeout: int = 10
	paranoid_mode: bool = False
	fail_open: bool = False  # DANGER: Setting True defeats the purpose of governance
	verbose: bool = True

	def __post_init__(self):
		# Try to load from environment if not provided
		if self.api_key is None:
			self.api_key = os.getenv('SWIFTAPI_KEY') or os.getenv('SWIFTAPI_API_KEY')

		if self.base_url == 'https://swiftapi.ai':
			env_url = os.getenv('SWIFTAPI_URL')
			if env_url:
				self.base_url = env_url

	@property
	def is_configured(self) -> bool:
		"""Check if SwiftAPI is properly configured."""
		return self.api_key is not None and self.api_key.startswith('swiftapi_')

	def validate(self) -> None:
		"""Validate configuration. Raises ValueError if invalid."""
		if not self.is_configured:
			raise ValueError(
				'SwiftAPI key not configured. Set SWIFTAPI_KEY environment variable '
				"or pass api_key parameter. Keys start with 'swiftapi_live_' or 'swiftapi_test_'."
			)

		if self.fail_open:
			import warnings

			warnings.warn(
				'SwiftAPI fail_open=True is DANGEROUS. Actions will execute without '
				'attestation if SwiftAPI is unreachable. This defeats the purpose of governance.',
				UserWarning,
			)
