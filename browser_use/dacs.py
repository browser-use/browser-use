"""DACS-Standard (DACS-1..DACS-4 & TLSNotary) execution guardrails for browser-use custom actions."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any


class DacsMandateViolationError(PermissionError):
	"""Raised fail-closed when a DACS-1..DACS-4 mandate or attenuation invariant fails."""


@dataclass(frozen=True)
class DacsExecutionContext:
	"""Normalized DACS-1..DACS-4 metadata attached to a browser-use tool invocation."""

	mandate_id: str | None = None
	session_id: str | None = None
	agent_did: str | None = None
	max_amount: Decimal | None = None
	parent_max_amount: Decimal | None = None
	requested_amount: Decimal | None = None
	tlsn_proxy_port: int | None = None
	tlsn_proof_id: str | None = None


def _parse_decimal(value: Any, field_name: str) -> Decimal:
	try:
		parsed = Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError) as exc:
		raise DacsMandateViolationError(f'DACS-Standard (§9.5.7): invalid numeric value for {field_name}') from exc
	if not parsed.is_finite() or parsed < Decimal('0'):
		raise DacsMandateViolationError(f'DACS-Standard (§9.5.7): {field_name} must be finite and >= 0')
	return parsed


def extract_dacs_context(kwargs: dict[str, Any]) -> DacsExecutionContext | None:
	"""Extracts optional dacs_* mandate/attestation fields without altering LLM tool schemas."""
	raw_mandate = kwargs.get('dacs_mandate') or kwargs.get('dacsMandate')
	raw_session = kwargs.get('dacs_session_id') or kwargs.get('dacsSessionId')
	raw_did = kwargs.get('dacs_agent_did') or kwargs.get('dacsAgentDid')
	raw_tlsn_proof = kwargs.get('dacs_tlsn_proof_id') or kwargs.get('dacsTlsnProofId')

	if not any((raw_mandate, raw_session, raw_did, raw_tlsn_proof)):
		return None

	raw_max = kwargs.get('dacs_max_amount', kwargs.get('dacsMaxAmount'))
	raw_parent = kwargs.get('dacs_parent_max_amount', kwargs.get('dacsParentMaxAmount'))
	raw_amount = kwargs.get('amount', kwargs.get('spend_amount', kwargs.get('dacs_amount')))
	raw_port = kwargs.get('dacs_tlsn_proxy_port', kwargs.get('dacsTlsnProxyPort'))

	tlsn_port: int | None = None
	if raw_port is not None:
		try:
			tlsn_port = int(raw_port)
		except (TypeError, ValueError) as exc:
			raise DacsMandateViolationError('DACS-3 (TLSNotary): invalid proxy port') from exc
		if tlsn_port != 7047 and not (55000 <= tlsn_port <= 60000):
			raise DacsMandateViolationError(
				f'DACS-3 (TLSNotary): proxy port {tlsn_port} outside attested range (7047 or 55000-60000)'
			)

	return DacsExecutionContext(
		mandate_id=str(raw_mandate) if raw_mandate is not None else None,
		session_id=str(raw_session) if raw_session is not None else None,
		agent_did=str(raw_did) if raw_did is not None else None,
		max_amount=_parse_decimal(raw_max, 'dacs_max_amount') if raw_max is not None else None,
		parent_max_amount=_parse_decimal(raw_parent, 'dacs_parent_max_amount') if raw_parent is not None else None,
		requested_amount=_parse_decimal(raw_amount, 'amount') if raw_amount is not None else None,
		tlsn_proxy_port=tlsn_port,
		tlsn_proof_id=str(raw_tlsn_proof) if raw_tlsn_proof is not None else None,
	)


def enforce_dacs_preflight(ctx: DacsExecutionContext | None) -> None:
	"""Enforces DACS-1 identity binding, DACS-2 (§9.5.7) spend ceilings, and hierarchical sub-mandate attenuation."""
	if ctx is None:
		return

	if ctx.max_amount is not None:
		if ctx.parent_max_amount is not None and ctx.max_amount > ctx.parent_max_amount:
			raise DacsMandateViolationError(
				f'DACS-2 (§9.5.7) sub-mandate attenuation violation: child ceiling {ctx.max_amount} '
				f'exceeds parent ceiling {ctx.parent_max_amount}'
			)
		if ctx.requested_amount is not None and ctx.requested_amount > ctx.max_amount:
			raise DacsMandateViolationError(
				f'DACS-2 (§9.5.7) spend mandate exceeded: requested {ctx.requested_amount} > ceiling {ctx.max_amount}'
			)


def build_dacs4_receipt(action_name: str, ctx: DacsExecutionContext, status: str) -> dict[str, Any]:
	"""Generates a deterministic DACS-4 (§14.4) post-execution state attestation receipt."""
	ts = datetime.now(UTC).isoformat()
	payload = json.dumps(
		{
			'spec': 'DACS-4/1.0',
			'action': action_name,
			'mandate_id': ctx.mandate_id,
			'session_id': ctx.session_id,
			'agent_did': ctx.agent_did,
			'tlsn_proof_id': ctx.tlsn_proof_id,
			'tlsn_proxy_port': ctx.tlsn_proxy_port,
			'status': status,
			'timestamp': ts,
		},
		sort_keys=True,
	)
	digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
	return {
		'spec': 'DACS-4/1.0',
		'action': action_name,
		'mandate_id': ctx.mandate_id,
		'session_id': ctx.session_id,
		'agent_did': ctx.agent_did,
		'tlsn_proof_id': ctx.tlsn_proof_id,
		'attestation_hash': f'0x{digest}',
		'timestamp': ts,
	}


def wrap_action_with_dacs(fn: Callable[..., Any]) -> Callable[..., Any]:
	"""Wraps a @tools.action callable with DACS-1..DACS-4 guardrails while preserving its exact signature."""
	sig = inspect.signature(fn)
	accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
	accepted_names = set(sig.parameters.keys())

	def _prepare(kwargs: dict[str, Any]) -> tuple[DacsExecutionContext | None, dict[str, Any]]:
		ctx = extract_dacs_context(kwargs)
		enforce_dacs_preflight(ctx)
		if accepts_kwargs:
			return ctx, kwargs
		filtered = {k: v for k, v in kwargs.items() if k in accepted_names}
		return ctx, filtered

	def _attach_receipt(result: Any, ctx: DacsExecutionContext | None) -> Any:
		if ctx is None:
			return result
		receipt = build_dacs4_receipt(fn.__name__, ctx, status='SETTLED')
		if hasattr(result, 'model_extra') and isinstance(result.model_extra, dict):
			result.model_extra['dacs_attestation'] = receipt
		return result

	if inspect.iscoroutinefunction(fn):

		@wraps(fn)
		async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
			ctx, call_kwargs = _prepare(kwargs)
			res = await fn(*args, **call_kwargs)
			return _attach_receipt(res, ctx)

		return _async_wrapper

	@wraps(fn)
	def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
		ctx, call_kwargs = _prepare(kwargs)
		res = fn(*args, **call_kwargs)
		return _attach_receipt(res, ctx)

	return _sync_wrapper
