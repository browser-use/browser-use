"""
SwiftAPI Attestation Client for Browser-Use

Provides cryptographic attestation verification for browser actions.
Every action is verified against SwiftAPI policies before execution.

Protocol: Ed25519 signatures, JTI-based replay prevention, policy-based authorization.
"""

import base64
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from .config import SwiftAPIConfig

logger = logging.getLogger(__name__)


class AttestationError(Exception):
    """Base exception for attestation errors."""
    pass


class PolicyViolationError(AttestationError):
    """Raised when an action violates SwiftAPI policy."""

    def __init__(self, message: str, denial_reason: str = "", policy_id: str = ""):
        super().__init__(message)
        self.denial_reason = denial_reason
        self.policy_id = policy_id


class AttestationRevokedError(AttestationError):
    """Raised when an attestation has been revoked."""

    def __init__(self, jti: str):
        super().__init__(f"Attestation {jti} has been revoked")
        self.jti = jti


class SignatureVerificationError(AttestationError):
    """Raised when signature verification fails."""
    pass


@dataclass
class AttestationResult:
    """Result of an attestation verification request."""

    approved: bool
    verification_id: str = ""
    jti: str = ""
    decision_hash: str = ""
    action_fingerprint: str = ""
    reason: str = ""
    attestation: Optional[Dict[str, Any]] = None
    policy_bundle_hash: Optional[str] = None
    expires_at: Optional[str] = None

    def to_header(self) -> str:
        """Convert attestation to base64 header value for MEP proxy."""
        if self.attestation is None:
            raise AttestationError("No attestation to encode")
        return base64.b64encode(json.dumps(self.attestation).encode()).decode()


class AttestationProvider(ABC):
    """Abstract base class for attestation providers."""

    @abstractmethod
    async def verify_action(
        self,
        action_type: str,
        action_params: Dict[str, Any],
        intent: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AttestationResult:
        """Verify an action and return attestation result."""
        pass

    @abstractmethod
    async def check_revocation(self, jti: str) -> bool:
        """Check if an attestation has been revoked."""
        pass


class SwiftAPIClient:
    """HTTP client for SwiftAPI authority."""

    def __init__(self, config: SwiftAPIConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers={
                    "X-SwiftAPI-Authority": self.config.api_key or "",
                    "Content-Type": "application/json",
                    "User-Agent": "browser-use-swiftapi/1.0.0",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def verify(
        self,
        action_type: str,
        intent: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call SwiftAPI /verify endpoint."""
        client = await self._get_client()

        # Build action fingerprint (hash of action details)
        action_data = {
            "type": action_type,
            "params": params,
        }
        action_fingerprint = hashlib.sha256(
            json.dumps(action_data, sort_keys=True).encode()
        ).hexdigest()

        # Build request payload
        payload = {
            "action": {
                "type": action_type,
                "intent": intent,
                "params": params,
            },
            "context": {
                "app_id": self.config.app_id,
                "actor": self.config.actor,
                "environment": "production",
                "request_id": f"bu_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
                **(context or {}),
            },
        }

        try:
            response = await client.post("/verify", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AttestationError("Invalid SwiftAPI key")
            elif e.response.status_code == 403:
                try:
                    data = e.response.json()
                    raise PolicyViolationError(
                        f"Action denied: {data.get('reason', 'Unknown')}",
                        denial_reason=data.get("reason", ""),
                        policy_id=data.get("policy_id", ""),
                    )
                except json.JSONDecodeError:
                    raise PolicyViolationError(f"Action denied: {e.response.text}")
            else:
                raise AttestationError(f"SwiftAPI error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise AttestationError(f"SwiftAPI unreachable: {e}")

    async def check_revocation(self, jti: str) -> bool:
        """Check if a JTI has been revoked."""
        client = await self._get_client()
        try:
            response = await client.get("/attestation/revocations")
            response.raise_for_status()
            data = response.json()
            revoked_jtis = set(data.get("revoked", []))
            return jti in revoked_jtis
        except Exception:
            # Conservative: assume revoked if we can't check
            return True

    async def get_info(self) -> Dict[str, Any]:
        """Get SwiftAPI authority info."""
        client = await self._get_client()
        try:
            response = await client.get("/")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise AttestationError(f"SwiftAPI error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise AttestationError(f"SwiftAPI unreachable: {e}")


class SwiftAPIAttestationProvider(AttestationProvider):
    """SwiftAPI-backed attestation provider.

    This is the production attestation provider that calls the live SwiftAPI
    authority for every action verification.
    """

    def __init__(self, config: SwiftAPIConfig):
        self.config = config
        self.client = SwiftAPIClient(config)
        self._public_key: Optional[bytes] = None

    async def verify_action(
        self,
        action_type: str,
        action_params: Dict[str, Any],
        intent: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AttestationResult:
        """Verify an action against SwiftAPI policies.

        Returns:
            AttestationResult with approved=True and signed attestation if allowed.

        Raises:
            PolicyViolationError: If action is denied by policy.
            AttestationError: If verification fails for other reasons.
        """
        try:
            response = await self.client.verify(
                action_type=action_type,
                intent=intent,
                params=action_params,
                context=context,
            )

            approved = response.get("approved", False)

            if not approved:
                reason = response.get("reason", "Policy denied action")
                raise PolicyViolationError(
                    f"Action '{action_type}' denied: {reason}",
                    denial_reason=reason,
                )

            return AttestationResult(
                approved=True,
                verification_id=response.get("verification_id", ""),
                jti=response.get("execution_attestation", {}).get("jti", ""),
                decision_hash=response.get("decision_hash", ""),
                action_fingerprint=response.get("action_fingerprint", ""),
                reason=response.get("reason", ""),
                attestation=response.get("execution_attestation"),
                policy_bundle_hash=response.get("policy_bundle_hash"),
                expires_at=response.get("execution_attestation", {}).get("expires_at"),
            )

        except PolicyViolationError:
            raise
        except AttestationError:
            if self.config.fail_open:
                logger.warning(
                    f"SwiftAPI unreachable, fail_open=True, allowing action: {action_type}"
                )
                return AttestationResult(
                    approved=True,
                    reason="SwiftAPI unreachable, fail_open mode",
                )
            raise

    async def check_revocation(self, jti: str) -> bool:
        """Check if an attestation has been revoked."""
        return await self.client.check_revocation(jti)

    async def close(self):
        """Close the HTTP client."""
        await self.client.close()


class NullAttestationProvider(AttestationProvider):
    """No-op attestation provider for testing and development.

    WARNING: This provider approves all actions without verification.
    Only use in development/testing environments.
    """

    def __init__(self, log_actions: bool = True):
        self.log_actions = log_actions
        self._action_log: list = []

    async def verify_action(
        self,
        action_type: str,
        action_params: Dict[str, Any],
        intent: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AttestationResult:
        """Always approve without actual verification."""
        if self.log_actions:
            logger.info(f"[NullProvider] Action: {action_type} (no attestation)")
            self._action_log.append({
                "action_type": action_type,
                "params": action_params,
                "intent": intent,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return AttestationResult(
            approved=True,
            reason="NullProvider: No attestation (development mode)",
        )

    async def check_revocation(self, jti: str) -> bool:
        """Always return False (not revoked) since we don't issue real attestations."""
        return False

    def get_action_log(self) -> list:
        """Get the log of all actions processed."""
        return self._action_log.copy()
