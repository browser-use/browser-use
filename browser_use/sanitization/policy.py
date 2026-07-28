# Placeholder for DLP policy engine definitions
# Intentionally compact: real logic will be added in follow-up commits
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import os

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


def load_dlp_config_from_env() -> DLPSanitizerConfig:
    """Lightweight env bridge until full config surface is added.

    Env vars:
      - BROWSER_USE_DLP_ENABLED: true/false
      - BROWSER_USE_DLP_MODE: off|audit|mask|block_high_risk
      - BROWSER_USE_DLP_STRATEGIES: comma list (mask,hash,drop)
      - BROWSER_USE_DLP_DETECTORS: comma list of detector names
    """
    enabled_token = os.getenv("BROWSER_USE_DLP_ENABLED", "false").strip().lower()
    enabled = enabled_token in {"true", "1", "yes", "y", "on"}
    mode = os.getenv("BROWSER_USE_DLP_MODE", "audit").lower()
    strategies_env = os.getenv("BROWSER_USE_DLP_STRATEGIES", "mask")
    detectors_env = os.getenv("BROWSER_USE_DLP_DETECTORS", "")

    strategies = [s.strip() for s in strategies_env.split(",") if s.strip()] or ["mask"]
    detectors = [d.strip() for d in detectors_env.split(",") if d.strip()]

    cfg = DLPSanitizerConfig(
        enabled=enabled,
        mode=mode if mode in ("off", "audit", "mask", "block_high_risk") else "audit",
        strategies=strategies,
    )
    if detectors:
        cfg.built_in_detectors = detectors
    return cfg
