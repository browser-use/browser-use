"""
SwiftAPI-Enabled Tools for Browser-Use

Wraps the browser-use Tools class with SwiftAPI attestation.
Every browser action requires cryptographic authorization before execution.
"""

import functools
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from browser_use.tools.service import Tools
from browser_use.tools.registry.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.llm.base import BaseChatModel
from browser_use.filesystem.file_system import FileSystem

from .config import SwiftAPIConfig
from .attestation import (
    AttestationProvider,
    SwiftAPIAttestationProvider,
    NullAttestationProvider,
    AttestationResult,
    AttestationError,
    PolicyViolationError,
)

logger = logging.getLogger(__name__)

Context = TypeVar("Context")


# Action types that are considered high-risk and require attestation
HIGH_RISK_ACTIONS = {
    "click",
    "input",
    "input_text",
    "fill",
    "navigate",
    "go_to_url",
    "search",
    "submit",
    "upload",
    "download",
    "evaluate",  # JavaScript execution
    "execute_script",
    "press",
    "keyboard",
    "drag",
    "drop",
    "select",
    "hover",
}

# Actions that are read-only and don't require attestation by default
READ_ONLY_ACTIONS = {
    "screenshot",
    "get_text",
    "get_html",
    "get_url",
    "get_title",
    "extract",
    "find_text",
    "wait",
    "sleep",
    "scroll",  # Scroll is borderline, but doesn't change state
}


def _generate_action_fingerprint(action_name: str, params: Dict[str, Any]) -> str:
    """Generate a deterministic fingerprint for an action."""
    data = {
        "action": action_name,
        "params": params,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _format_action_intent(action_name: str, params: Dict[str, Any], page_url: Optional[str] = None) -> str:
    """Generate a human-readable intent string for the action."""
    intent_parts = [f"browser-use executing {action_name}"]

    if page_url:
        intent_parts.append(f"on {page_url}")

    # Add relevant params
    if "url" in params:
        intent_parts.append(f"to {params['url']}")
    elif "text" in params:
        # Truncate long text
        text = str(params["text"])[:50]
        intent_parts.append(f"with text '{text}'")
    elif "index" in params:
        intent_parts.append(f"element {params['index']}")

    return " ".join(intent_parts)


class SwiftAPITools(Tools, Generic[Context]):
    """Browser-use Tools with SwiftAPI attestation.

    Every action is verified against SwiftAPI policies before execution.
    If attestation fails, the action is blocked.

    Usage:
        tools = SwiftAPITools(swiftapi_key="swiftapi_live_...")

        # Or with full config
        config = SwiftAPIConfig(
            api_key="swiftapi_live_...",
            verbose=True,
        )
        tools = SwiftAPITools(config=config)
    """

    def __init__(
        self,
        swiftapi_key: Optional[str] = None,
        config: Optional[SwiftAPIConfig] = None,
        attestation_provider: Optional[AttestationProvider] = None,
        attest_all_actions: bool = False,  # If True, attest read-only actions too
        exclude_actions: list[str] | None = None,
        output_model: type | None = None,
        display_files_in_done_text: bool = True,
    ):
        """Initialize SwiftAPI-enabled Tools.

        Args:
            swiftapi_key: SwiftAPI authority key. Alternative to config.
            config: Full SwiftAPIConfig object.
            attestation_provider: Custom attestation provider (for testing).
            attest_all_actions: If True, require attestation for all actions.
            exclude_actions: Actions to exclude from the registry.
            output_model: Pydantic model for structured output.
            display_files_in_done_text: Whether to display file paths in done text.
        """
        # Initialize parent Tools
        super().__init__(
            exclude_actions=exclude_actions,
            output_model=output_model,
            display_files_in_done_text=display_files_in_done_text,
        )

        # Set up SwiftAPI config
        if config is not None:
            self._swiftapi_config = config
        else:
            self._swiftapi_config = SwiftAPIConfig(api_key=swiftapi_key)

        # Set up attestation provider
        if attestation_provider is not None:
            self._attestation_provider = attestation_provider
        elif self._swiftapi_config.is_configured:
            self._attestation_provider = SwiftAPIAttestationProvider(self._swiftapi_config)
        else:
            # No key provided - fail-closed by default
            logger.warning(
                "SwiftAPI key not configured. All high-risk actions will be blocked. "
                "Set SWIFTAPI_KEY or pass swiftapi_key parameter."
            )
            self._attestation_provider = None

        self._attest_all_actions = attest_all_actions

    def _requires_attestation(self, action_name: str) -> bool:
        """Check if an action requires attestation."""
        if self._attest_all_actions:
            return True
        return action_name.lower() in HIGH_RISK_ACTIONS

    async def _get_attestation(
        self,
        action_name: str,
        params: Dict[str, Any],
        page_url: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AttestationResult:
        """Get attestation for an action.

        Returns:
            AttestationResult if approved.

        Raises:
            PolicyViolationError: If action is denied.
            AttestationError: If attestation fails.
        """
        if self._attestation_provider is None:
            # No provider configured - fail closed
            raise AttestationError(
                f"SwiftAPI not configured. Action '{action_name}' blocked. "
                "Set SWIFTAPI_KEY environment variable or pass swiftapi_key parameter."
            )

        intent = _format_action_intent(action_name, params, page_url)

        attestation_context = {
            "page_url": page_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(context or {}),
        }

        result = await self._attestation_provider.verify_action(
            action_type=action_name,
            action_params=params,
            intent=intent,
            context=attestation_context,
        )

        if self._swiftapi_config.verbose and result.approved:
            jti_short = result.jti[:12] if result.jti else "none"
            logger.info(f"\033[32m[SwiftAPI]\033[0m Approved: {action_name} (JTI: {jti_short}...)")

        return result

    async def act(
        self,
        action: ActionModel,
        browser_session: BrowserSession,
        page_extraction_llm: BaseChatModel | None = None,
        sensitive_data: dict[str, str | dict[str, str]] | None = None,
        available_file_paths: list[str] | None = None,
        file_system: FileSystem | None = None,
    ) -> ActionResult:
        """Execute an action with SwiftAPI attestation.

        This wraps the parent act() method with attestation verification.
        If attestation fails, the action is blocked and an error is returned.
        """
        # Extract the action name and params
        for action_name, params in action.model_dump(exclude_unset=True).items():
            if params is not None:
                # Check if this action requires attestation
                if self._requires_attestation(action_name):
                    try:
                        # Get current page URL for context
                        page_url = None
                        if browser_session:
                            try:
                                page_url = await browser_session.get_current_page_url()
                            except Exception:
                                pass

                        # Get attestation
                        attestation = await self._get_attestation(
                            action_name=action_name,
                            params=params if isinstance(params, dict) else params.model_dump(),
                            page_url=page_url,
                        )

                        if not attestation.approved:
                            error_msg = f"Action '{action_name}' blocked by SwiftAPI: {attestation.reason}"
                            logger.warning(f"\033[31m[SwiftAPI]\033[0m {error_msg}")
                            return ActionResult(error=error_msg)

                    except PolicyViolationError as e:
                        error_msg = f"Action '{action_name}' denied by policy: {e.denial_reason}"
                        logger.warning(f"\033[31m[SwiftAPI]\033[0m {error_msg}")
                        return ActionResult(error=error_msg)

                    except AttestationError as e:
                        error_msg = f"SwiftAPI attestation failed for '{action_name}': {e}"
                        logger.error(f"\033[31m[SwiftAPI]\033[0m {error_msg}")
                        return ActionResult(error=error_msg)

                else:
                    # Read-only action, no attestation required
                    if self._swiftapi_config.verbose:
                        logger.debug(f"[SwiftAPI] Passthrough (read-only): {action_name}")

                break  # Only one action per ActionModel

        # Call parent act() method if attestation passed
        return await super().act(
            action=action,
            browser_session=browser_session,
            page_extraction_llm=page_extraction_llm,
            sensitive_data=sensitive_data,
            available_file_paths=available_file_paths,
            file_system=file_system,
        )

    async def close(self):
        """Close the attestation provider."""
        if self._attestation_provider and hasattr(self._attestation_provider, "close"):
            await self._attestation_provider.close()
