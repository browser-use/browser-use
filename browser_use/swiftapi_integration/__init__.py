"""
SwiftAPI Integration for Browser-Use
Cryptographic Attestation for AI Browser Actions

This integration adds execution governance to browser-use via SwiftAPI attestation.
Every browser action (click, type, navigate, etc.) requires cryptographic authorization
before execution.

Usage:
    from swiftapi_integration import SwiftAPITools, SwiftAPIAgent

    # Option 1: Use SwiftAPI-enabled Tools
    tools = SwiftAPITools(swiftapi_key="swiftapi_live_...")

    # Option 2: Use SwiftAPI-enabled Agent
    agent = SwiftAPIAgent(
        task="...",
        llm=llm,
        swiftapi_key="swiftapi_live_..."
    )

Without a valid SwiftAPI key, actions are blocked by default (fail-closed).
This makes browser-use enterprise-ready with auditable, verifiable execution.

Author: Rayan Pal
License: MIT
DOI: 10.5281/zenodo.18012025
"""

from .attestation import (
    SwiftAPIClient,
    AttestationProvider,
    SwiftAPIAttestationProvider,
    NullAttestationProvider,
    AttestationResult,
    AttestationError,
    PolicyViolationError,
)
from .tools import SwiftAPITools
from .agent import SwiftAPIAgent
from .config import SwiftAPIConfig

__all__ = [
    # Core
    "SwiftAPIClient",
    "AttestationProvider",
    "SwiftAPIAttestationProvider",
    "NullAttestationProvider",
    "AttestationResult",
    "AttestationError",
    "PolicyViolationError",
    # High-level
    "SwiftAPITools",
    "SwiftAPIAgent",
    "SwiftAPIConfig",
]

__version__ = "1.0.0"
