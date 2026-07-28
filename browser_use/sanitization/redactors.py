from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .policy import DLPSanitizerConfig
from .patterns import get_default_patterns

MASK = "****"

@dataclass
class RedactionFinding:
    type: str
    severity: str
    start: int
    end: int


def _apply_strategy(text: str, start: int, end: int, strategy: str) -> str:
    if strategy == "drop":
        return text[:start] + text[end:]
    # default: mask
    return text[:start] + MASK + text[end:]


def sanitize_text(text: str, cfg: DLPSanitizerConfig) -> tuple[str, list[RedactionFinding]]:
    if not cfg.enabled or cfg.mode == "off":
        return text, []
    patterns = get_default_patterns()
    findings: list[RedactionFinding] = []

    # Collect matches first to avoid shifting indices while replacing
    matches: list[tuple[int, int, str]] = []
    for name, pat in patterns.items():
        if name not in cfg.built_in_detectors:
            continue
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), name))

    # Sort by start desc to keep indices valid during replacement
    matches.sort(key=lambda x: x[0], reverse=True)

    for start, end, name in matches:
        findings.append(RedactionFinding(type=name, severity="high", start=start, end=end))
        # Apply first configured strategy
        strategy = cfg.strategies[0] if cfg.strategies else "mask"
        text = _apply_strategy(text, start, end, strategy)

    return text, findings


def sanitize_messages(messages: list[Any], cfg: DLPSanitizerConfig) -> tuple[list[Any], list[RedactionFinding]]:
    findings: list[RedactionFinding] = []
    sanitized: list[Any] = []
    for msg in messages:
        msg_copy = msg
        try:
            if hasattr(msg_copy, "content"):
                content = getattr(msg_copy, "content")
                if isinstance(content, str):
                    new_text, f = sanitize_text(content, cfg)
                    findings.extend(f)
                    setattr(msg_copy, "content", new_text)
                elif isinstance(content, list):
                    for i, part in enumerate(content):
                        if getattr(part, "type", None) == "text" and hasattr(part, "text"):
                            new_text, f = sanitize_text(part.text, cfg)
                            findings.extend(f)
                            part.text = new_text
                            content[i] = part
                    setattr(msg_copy, "content", content)
        except Exception:
            pass
        sanitized.append(msg_copy)
    return sanitized, findings
