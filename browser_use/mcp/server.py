"""MCP Server for browser-use - exposes browser automation capabilities to MCP clients.

This module hosts the MCP server runtime and request/response handling.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from browser_use.sanitization.policy import load_dlp_config_from_env
from browser_use.sanitization.redactors import sanitize_text

# Existing server implementation continues below (omitted here for brevity)
# ...


def mcp_sanitize_egress(payload: Any) -> tuple[Any, Mapping[str, Any]]:
    """Non-mutating egress guard for MCP tool responses and streams.

    - Deep-copies the outgoing payload
    - Applies DLP sanitizer to any string fields
    - Returns (sanitized_payload, metadata) where metadata includes sanitized flag and findings count
    """
    cfg = load_dlp_config_from_env()
    try:
        data = copy.deepcopy(payload)
    except Exception:
        data = payload

    findings_total = 0

    def _sanitize_obj(obj: Any) -> Any:
        nonlocal findings_total
        if isinstance(obj, str):
            new, findings = sanitize_text(obj, cfg)
            findings_total += len(findings)
            return new
        if isinstance(obj, list):
            return [_sanitize_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _sanitize_obj(v) for k, v in obj.items()}
        return obj

    sanitized = _sanitize_obj(data)
    meta = {"sanitized": bool(findings_total), "dlp_findings": findings_total}
    return sanitized, meta
