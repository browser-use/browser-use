"""Strict human-reference eligibility, audits, and CSV metadata helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import HumanRunRecord, TaskCard

_PLACEHOLDER_EVIDENCE_SUBSTRINGS: tuple[str, ...] = (
	'待补充',
	'replace this with the exact manual steps',
	'fill this after the human baseline run',
)
FieldVisibility = Literal['visible', 'verified_not_visible']


class EligibilityResult(BaseModel):
	"""Structured output for strict reference-eligibility validation."""

	model_config = ConfigDict(extra='forbid')

	eligible: bool
	reasons: list[str] = Field(default_factory=list)
	derived_reference_eligible: bool


class HumanRunAuditWarning(BaseModel):
	"""One data-quality warning for a human run record."""

	model_config = ConfigDict(extra='forbid')

	run_identifier: str
	task_id: str
	scenario_id: str
	code: str
	conflicting_fields: list[str] = Field(default_factory=list)
	recommended_status: str
	message: str


def _evidence_string_is_valid(text: str) -> bool:
	stripped = text.strip()
	if not stripped:
		return False
	lower = stripped.lower()
	return not any(marker in stripped or marker in lower for marker in _PLACEHOLDER_EVIDENCE_SUBSTRINGS)


def _criteria_check_passed(item: dict[str, Any]) -> bool:
	return isinstance(item, dict) and item.get('met') is True


def _normalize_field_visibility(value: Any) -> FieldVisibility | None:
	if value == 'visible':
		return 'visible'
	if value == 'verified_not_visible':
		return 'verified_not_visible'
	return None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
	low = text.lower()
	return any(key in low for key in keywords)


def _supports_verified_not_visible(check: dict[str, Any], run: HumanRunRecord) -> bool:
	"""Allow strict pass when base model is explicitly verified not visible."""

	visibility = _normalize_field_visibility(check.get('field_visibility'))
	if visibility != 'verified_not_visible':
		return False
	evidence_blob = ' '.join([*(run.final_evidence or []), str(check.get('evidence', ''))]).lower()
	has_not_visible = _contains_any(
		evidence_blob,
		(
			'not visible',
			'不可见',
			'未找到',
			'not found',
		),
	)
	has_verification_scope = _contains_any(
		evidence_blob,
		(
			'model card',
			'metadata',
			'readme',
			'visible region',
			'可见区域',
			'元数据',
		),
	)
	return has_not_visible and has_verification_scope


def _criterion_passes_strictly(run: HumanRunRecord, check: dict[str, Any]) -> tuple[bool, str | None]:
	if not isinstance(check, dict):
		return False, 'criterion_invalid'
	if check.get('met') is True:
		return True, None
	name = str(check.get('criterion', '')).lower()
	if 'base model' in name and _supports_verified_not_visible(check, run):
		return True, None
	return False, f'criterion_failed:{check.get("criterion", "unknown")}'


def human_run_has_valid_evidence(run: HumanRunRecord) -> bool:
	"""True when ``final_evidence`` or ``criteria_checks`` contains at least one non-placeholder item."""

	if any(_evidence_string_is_valid(item) for item in run.final_evidence):
		return True
	return any(_criteria_check_passed(item) for item in run.criteria_checks)


def validate_reference_eligibility(run: HumanRunRecord, task_card: TaskCard | None = None) -> EligibilityResult:
	"""Strict eligibility validator used by all reference selection and LCS logic."""

	reasons: list[str] = []
	if run.run_status != 'completed':
		reasons.append(f'run_status:{run.run_status}')
	if run.outcome_label != 'success':
		reasons.append(f'outcome_label:{run.outcome_label}')
	if not run.criteria_checks:
		reasons.append('criteria_missing')
	for check in run.criteria_checks:
		ok, reason = _criterion_passes_strictly(run, check)
		if not ok and reason:
			reasons.append(reason)
	if not human_run_has_valid_evidence(run):
		reasons.append('final_evidence_missing')
	if run.trajectory_comparable == 'low':
		reasons.append('trajectory_comparable:low')
	return EligibilityResult(
		eligible=not reasons,
		reasons=reasons,
		derived_reference_eligible=not reasons,
	)


def is_human_reference_eligible(run: HumanRunRecord, task_card: TaskCard | None = None) -> bool:
	"""Backwards-compatible boolean wrapper over strict validation."""

	return validate_reference_eligibility(run, task_card).eligible


def _milestone_outcome_values(run: HumanRunRecord) -> set[str]:
	return {
		str(item.get('outcome', '')).lower()
		for item in run.milestone_outcomes
		if isinstance(item, dict) and item.get('outcome') is not None
	}


def _run_identifier(run: HumanRunRecord) -> str:
	return f'{run.task_id}/{run.scenario_id}/{run.operator}'


def audit_human_run_record(run: HumanRunRecord, task_card: TaskCard | None = None) -> list[HumanRunAuditWarning]:
	"""Detect contradictory status/eligibility/evidence claims without rewriting facts."""

	out: list[HumanRunAuditWarning] = []
	identifier = _run_identifier(run)
	eligibility = validate_reference_eligibility(run, task_card)
	any_criterion_failed = any(not _criterion_passes_strictly(run, c)[0] for c in run.criteria_checks)
	all_criteria_passed = bool(run.criteria_checks) and not any_criterion_failed

	if run.outcome_label == 'success' and any_criterion_failed:
		out.append(
			HumanRunAuditWarning(
				run_identifier=identifier,
				task_id=run.task_id,
				scenario_id=run.scenario_id,
				code='outcome_success_with_failed_criterion',
				conflicting_fields=['outcome_label', 'criteria_checks'],
				recommended_status='partial_success',
				message='Outcome is success while at least one strict criterion failed.',
			)
		)
	if run.reference_eligible is True and not eligibility.eligible:
		out.append(
			HumanRunAuditWarning(
				run_identifier=identifier,
				task_id=run.task_id,
				scenario_id=run.scenario_id,
				code='reference_eligible_mismatch',
				conflicting_fields=['reference_eligible', 'run_status', 'outcome_label', 'criteria_checks', 'final_evidence'],
				recommended_status='reference_eligible=false',
				message=f'Stored reference_eligible=true conflicts with strict validator: {eligibility.reasons}',
			)
		)

	milestone_outcomes = _milestone_outcome_values(run)
	if all_criteria_passed and ('partial' in milestone_outcomes or 'failed' in milestone_outcomes):
		out.append(
			HumanRunAuditWarning(
				run_identifier=identifier,
				task_id=run.task_id,
				scenario_id=run.scenario_id,
				code='milestone_vs_criteria_contradiction',
				conflicting_fields=['milestone_outcomes', 'criteria_checks'],
				recommended_status='review_milestone_or_criteria',
				message='Milestone includes partial/failed while strict criteria are all marked as passed.',
			)
		)

	final_text = (run.final_answer or {}).get('text', '') if isinstance(run.final_answer, dict) else ''
	evidence_blob = ' '.join([*(run.final_evidence or []), final_text]).lower()
	if run.task_id == 'complex_travel_package_booking':
		if 'age' in evidence_blob and '6' not in evidence_blob and '6岁' not in evidence_blob:
			out.append(
				HumanRunAuditWarning(
					run_identifier=identifier,
					task_id=run.task_id,
					scenario_id=run.scenario_id,
					code='travel_passenger_age_mismatch',
					conflicting_fields=['final_evidence', 'final_answer', 'criteria_checks'],
					recommended_status='review_passenger_age_claim',
					message='Travel record references child age but explicit age=6 evidence is missing.',
				)
			)
		if any('free parking' in str(c.get('criterion', '')).lower() and c.get('met') is True for c in run.criteria_checks):
			if not _contains_any(evidence_blob, ('free parking', '免费停车', '免费泊车', '停车')):
				out.append(
					HumanRunAuditWarning(
						run_identifier=identifier,
						task_id=run.task_id,
						scenario_id=run.scenario_id,
						code='travel_filter_evidence_gap',
						conflicting_fields=['criteria_checks', 'final_evidence', 'final_answer'],
						recommended_status='review_filter_claim',
						message='Free-parking criterion passed but supporting evidence text is missing.',
					)
				)
	if run.task_id == 'huggingface_model_constrained_selection':
		base_checks = [c for c in run.criteria_checks if 'base model' in str(c.get('criterion', '')).lower()]
		for check in base_checks:
			if check.get('met') is False and _supports_verified_not_visible(check, run):
				out.append(
					HumanRunAuditWarning(
						run_identifier=identifier,
						task_id=run.task_id,
						scenario_id=run.scenario_id,
						code='huggingface_verified_not_visible_strict_success',
						conflicting_fields=['criteria_checks', 'final_evidence', 'outcome_label'],
						recommended_status='treat_as_strict_success',
						message=(
							'Base model criterion can be strict-pass when field_visibility=verified_not_visible '
							'with Model Card + README verification evidence.'
						),
					)
				)
			if check.get('met') is True and _contains_any(str(check.get('evidence', '')).lower(), ('not visible', '不可见')):
				out.append(
					HumanRunAuditWarning(
						run_identifier=identifier,
						task_id=run.task_id,
						scenario_id=run.scenario_id,
						code='huggingface_base_model_claim_contradiction',
						conflicting_fields=['criteria_checks'],
						recommended_status='review_base_model_claim',
						message='Base model criterion marked met but evidence says field is not visible.',
					)
				)
	return out


def compute_human_milestone_coverage(run: HumanRunRecord) -> float | None:
	"""Fraction of ``milestone_outcomes`` entries with ``reached=True``; ``None`` when empty."""

	if not run.milestone_outcomes:
		return None
	reached = sum(1 for item in run.milestone_outcomes if isinstance(item, dict) and item.get('reached') is True)
	total = len(run.milestone_outcomes)
	if total <= 0:
		return None
	return float(reached) / float(total)


def human_reference_csv_fields(human: HumanRunRecord | None) -> dict[str, Any]:
	"""Flat CSV cells for human baseline metadata on agent comparison rows."""

	if human is None:
		return {
			'human_reference_eligible': '',
			'human_outcome_label': '',
			'human_trajectory_comparable': '',
			'human_route_relation': '',
			'human_final_domain': '',
			'human_cross_site_fallback': '',
			'human_milestone_coverage': '',
		}
	coverage = compute_human_milestone_coverage(human)
	eligibility = validate_reference_eligibility(human)
	return {
		'human_reference_eligible': eligibility.eligible,
		'human_outcome_label': human.outcome_label or '',
		'human_trajectory_comparable': human.trajectory_comparable or '',
		'human_route_relation': human.route_relation or '',
		'human_final_domain': human.final_domain or '',
		'human_cross_site_fallback': human.cross_site_fallback,
		'human_milestone_coverage': '' if coverage is None else coverage,
	}
