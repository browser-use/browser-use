# Placeholder for DLP policy engine definitions
# Intentionally compact: real logic will be added in follow-up commits
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

SanitizerMode = Literal["off", "audit", "mask", "block_high_risk"]

@dataclass
class DLPSanitizerConfig:
    enabled: bool = False
    mode: SanitizerMode = "audit"
    strategies: list[Literal["mask", "hash", "drop"]] = field(default_factory=lambda: ["mask"])
    built_in_detectors: list[str] = field(
        default_factory=lambda: [
            "email", "phone", "credit_card", "ssn", "jwt", "api_key", "oauth_token", "iban"
        ]
    )
    url_query_param_policies: list[str] = field(default_factory=lambda: ["access_token", "auth", "token", "bearer"])
    screenshot_policy: Literal["none", "blur_regions", "block"] = "none"
    custom_regex: list[tuple[str, str, str]] = field(default_factory=list)  # (pattern, severity, replacement)
